#!/usr/bin/env python2
# -*- coding: utf-8 -*-
"""
alerts.py - IRC bot geographical alerts module

This file is part of the "Brainstorm" distribution (https://github.com/luccoj/earthquakes-bot).
Copyright (c) 2016-2023 Lorenzo J. Lucchini (ljlbox@tiscali.it)

This program is free software: you can redistribute it and/or modify  
it under the terms of the GNU General Public License as published by  
the Free Software Foundation, version 3.
This program is distributed in the hope that it will be useful, but 
WITHOUT ANY WARRANTY; without even the implied warranty of 
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU 
General Public License for more details.
You should have received a copy of the GNU General Public License 
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import os
import obspy, obspy.taup, obspy.geodetics
from obspy.clients import fdsn
import re
import math
import time
import requests
import feedparser
import tweepy
import random
import shelve
import unicodedata
import statistics
import csv
from StringIO import StringIO
from itertools import chain
from cachetools import TTLCache, LFUCache
from sys import setcheckinterval
import threading
from threading import Thread, Timer, Lock, RLock, Semaphore, stack_size
from collections import OrderedDict, deque, Counter
from ws4py.client.threadedclient import WebSocketClient
import ssl
from functools import total_ordering
from astral import Astral
import json
import geojson
import humanize
from xml.etree import ElementTree
import countrynames
import gc
import sys

from modules import utils
from modules import storage
from modules import where
# This is not included in the distribution, and not strictly necessary. Would need more cleanup.
# from modules import engines
from modules.when import When
from modules.tables import keywords
from modules.tables import earthquakes
from modules.timing import Stopwatch, profile
# This module has too many rotten internal dependencies to include. Will have to find a replacement.
# The lack of it DOES break the whole thing, so it needs to be replaced with something working.
# from modules import langcodes
from modules.recipients import Recipient, File, IRC, Twitter, Mastodon, Reddit, XMPP, Matrix

from utils import Worker, Rejecter, clip, exceeds

debug = False

DEBUGGING_ROOM = "dummy-matrix-room"
IRC_OWNER = "dummy-user"

tsunami_sites = [
   "http://www.tsunami.gov/",
   "http://www.jma.go.jp/en/tsunami/",
   "http://www.bom.gov.au/tsunami/",
#   "https://goo.gl/CGAt5M",
#   "https://goo.gl/CuQMfg",
#   "https://goo.gl/pJfbGy",
]


class Dispatcher(Rejecter):
    priority = 0
    handlers = []

    def __init__(self, root, handlers=None):
       self.handlers = handlers or self.every(root)

    def __call__(self, *args, **kwargs):
       for handler in self.handlers:
          try:
             dispatchee = "{cls}({args})".format(cls=handler.__name__, args=", ".join(type(arg).__name__ for arg in list(args) + kwargs.values()))
             with Stopwatch("Dispatching to {dispatchee}".format(dispatchee=dispatchee), long=0.1):
                return handler(*args, **kwargs)
          except Rejecter.Rejection as error:
             #utils.log("Rejection by {cls}: {error}".format(cls=handler, error=error))
             continue
          except Exception as error:
             utils.error("Dispatched class {cls} failed".format(cls=handler))

       raise self.Rejection("None of {handlers} handles data".format(handlers=", ".join(handler.__name__ for handler in self.handlers)))

    @classmethod
    def every(cls, parent):
       return sorted(parent.__subclasses__(), key=lambda subclass: cls.priority(subclass), reverse=True)

    @classmethod
    def priority(cls, subclass):
       try: return subclass.priority
       except: return 0


class Receiver(Worker):
   type = 'Generic'
   resource = None
   manager = None

   def __new__(cls, resource, manager):
      if cls.accepts(resource): return super(Receiver, cls).__new__(cls, resource, manager)
      else: raise cls.Rejection

   def __init__(self, resource, manager):
      raise NotImplementedError("Do implement me please")

   @classmethod
   def accepts(cls, resource):
      raise NotImplementedError("Abstract receiver has no clue")

   @staticmethod
   def urlscheme(url):
      if not isinstance(url, basestring): return None
      return requests.utils.urlparse(url).scheme.lower()

   def focus(self):
      raise NotImplementedError("Cannot filter on generic resource")

   def disconnect(self):
      utils.log("No operation needed to disconnect from {type} resource".format(type=self.type))

   def cleanup(self, message="no error in particular"):
      utils.log("Closing {type} receiver for {resource}: {message}".format(type=self.type, resource=self.resource, message=message))

      try:
         self.finish()
         self.disconnect()
      except:
         utils.error("Problem closing {resource}".format(resource=self.resource))
      finally:
         time.sleep(30)
         return False

   def __hash__(self):
      return hash((self.type, self.resource, self.manager))

   def __eq__(self, other):
      if type(self) == type(other) and hash(self) == hash(other): return True
      else: return False

   def __format__(self, format):
      formats = {
         'type': lambda: self.type,
         'url': lambda: self.resource if requests.utils.urlparse(self.resource) else "{}://".format(self.type),
         'host': lambda: requests.utils.urlparse(self.resource).netloc,
      }

      try:
         return formats.get(format or 'host', lambda: self.resource or "unknown provicer")()
      except:
         return self.type or "unknown provider"


class FakeReceiver(object):
   resource = "SIMULATION ONLY! NOT A REAL REPORT!"

   def __format__(self, format): return self.resource


class PollingReceiver(Receiver):
   type = 'Polling'
   period = 300
   limit = 12
   semaphore = Semaphore(2)

   def fetch(self):
      return NotImplementedError("Abstract method")

   @classmethod
   def accepts(cls, resource):
      return False

   def __init__(self, resource, manager):
      self.resource, self.manager = resource, manager
      self.period = random.uniform(self.period-self.period/10, self.period+self.period/10)

      self.cache = None
      self.stopwatch = Stopwatch("Getting {receiver.resource} every {receiver.period} seconds".format(receiver=self), long=10.0)

      self.start(input=self.ticker(), output=manager.input)

   def throttle(self, events=None, towards=None):
      intervals = filter(None, [towards]) or [(event.update-event.time).seconds/3.0 for event in events if event and event.update > event.time]

      if intervals:
         weight = 0.3 if towards else 0.7 if min(intervals) < self.period else 0.05
         self.period = self.period*(1-weight) + clip(min(intervals), 50, 500)*(weight)
         if towards: utils.log("Next {self.type} poll at {self.resource} after {self.period:.0f} seconds, max {self.limit}".format(self=self))

   def process(self, tick, origin):
      utils.log("Parsing events from {receiver.resource} with semaphore at {sem}".format(receiver=self, sem=self.semaphore._Semaphore__value))
      if any(lock.locked() for lock in Monitor.locks.values()):
         wait = int(self.period * random.random())
         utils.log("Waiting {time} seconds before parsing {receiver.resource}".format(time=wait, receiver=self))
         time.sleep(wait)

      with self.semaphore:
         try:
            data = self.fetch()
         except Exception as error:
            utils.log("WARNING: Resource {name} failed to fetch: {error} ({type})".format(name=self.resource, error=error, type=type(error)))
            self.throttle(towards=300)
            return

         if data == self.cache or not data:
            self.throttle(towards=self.period*0.99)
            return
         else:
            self.cache = data

         with self.stopwatch:
            try:
               utils.log("Parsing events from {receiver.type} at {receiver.resource}".format(receiver=self))
               events = list(self.manager.parser(data, limit=int(self.limit/slowdown.factor)))
               utils.log("Done parsing {count} events from {receiver.type} at {receiver.resource}".format(count=len(events), receiver=self))
            except:
               utils.error("Could not parse {receiver.type} events at {receiver.resource} ({data})".format(receiver=self, data=data[:64]))
               self.throttle(towards=300)
               return

      for event in events:
         PollingReceiver.wait = True
         yield event

      if self.stopwatch.average < self.period*0.25:
         self.throttle(events)
         utils.log("Checking %s took %s, average %s" % (self.resource, self.stopwatch.partial, self.stopwatch.average))
      else:
         self.limit = clip(int(self.limit*0.8), 3, 48)
         utils.log("Checking period too short for %s! Set limit %s" % (self.resource, self.limit))

      self.throttle(towards=self.period + self.stopwatch.partial*slowdown.factor)


class HTTPReceiver(PollingReceiver, Receiver):
   type = 'HTTP'
   period = 100

   @classmethod
   def accepts(cls, resource):
      return cls.urlscheme(resource) in ('http', 'https')

   def fetch(self):
      if slowdown.factor > 1.5:
         utils.log("Too slow for HTTP: %r" % slowdown.factor)
         return []

      return utils.web.get(self.resource, timeout=32, verify=False).content


class FDSNReceiver(PollingReceiver, Receiver):
   type = 'FDSN'
   priority = 2
   period = 90

   @classmethod
   def accepts(cls, resource):
      try: return (cls.urlscheme(resource) in ['fdsn']) or ('event' in fdsn.Client(resource).services)
      except: return False

   def fetch(self):
      client = fdsn.Client(self.resource.replace("fdsn://", "http://"))

      now = obspy.UTCDateTime.now()
      #limit, minmag, start = (12, 3.0, now-(3600*24)) if 'limit' in client.services.get('event') else (None, 3.5, now-(3600*12))
      limit, minmag, start = (None, 3.0, now-(3600*12))

      try: return client.get_events(starttime=start, minmag=minmag, limit=limit)
      except fdsn.header.FDSNNoDataException: return []


# Note the v1 Twitter streaming API is no longer available, so this code will not really work anymore.
# It could be ported to the v2 streaming API, but it's now only available to paying user for a very high price.
# Be aware, and thank the new Twitter owner for this.

class TwitterReceiver(tweepy.streaming.StreamListener, Receiver):
    type = 'Twitter'
    locations = []

    total, valid, delay = 0, 0, 0.0
    lock = Lock()

    @classmethod
    def accepts(cls, resource):
        return isinstance(resource, Twitter)

    def __init__(self, resource, manager):
        return
        utils.log("Initializing Twitter receiver")

        stack_size(4096*64)
        setcheckinterval(25)

        tweepy.streaming.StreamListener.__init__(self)

        self.resource, self.manager = resource, manager

        TwitterParser.alerters = list(resource.friends)
        utils.log("%d twitter alerters registered: %r" % (len(TwitterParser.alerters), TwitterParser.alerters))

        # Get these in a separate way so we don't have to turn every user id into a Twitter object, which is slow due to Twitter.handle
        self.friends = [friend.handle.id for friend in resource.friends]
        self.blocks = [blocked.handle.id for blocked in resource.blocks]
        utils.log("Friend users are: %r" % self.friends)
        utils.log("Blocked users are: %r" % self.blocks)

        self.posters = deque(maxlen=64)
        self.tweets = deque(maxlen=16)
        self.overwhelmed = False

        self.start(output=manager.input, timeout=600, size=128, threads=2)
        Thread(target=self.focus).start()

    def focus(self, locations=[], words=[]):
        try:
           time.sleep(10)
           self.stream.disconnect()
           utils.log("Existing Twitter stream disconnected.")
           time.sleep(10)
        except:
           utils.log("Setting up initial Twitter stream.")
           time.sleep(120)
           utils.log("Starting to receive tweets.")

        alerters = map("{:id}".format, self.resource.friends)
        words = words or keywords.get('earthquake')+keywords.get('alert')

        utils.log("Watching for %r keywords on Twitter" % len(words))

        try:
           with self.lock:
              self.stream = self.resource.stream(self)
              self.stream.filter(follow=alerters, is_async=True, stall_warnings=True)

              utils.log("Filtering tweets: {words} words, {users} users, {coords} places".format(words=len(words), users=len(alerters), coords=len(locations)))

              error = "No error, stream is over"
        except Exception as error:
           utils.error("STREAM error")


    def suspend(self, timeout=60):
       def resume():
          self.overwhelmed = False
          TwitterParser.delayed = False
          utils.log("WARNING: Un-refocusing now")
#          self.focus()

       self.overwhelmed = True
       TwitterParser.delayed = True

       Timer(timeout, resume).start()


    def process(self, status, origin):
       updated = (When.now() - When.fromstring(status.created_at)).seconds

       friend = status.user.id in self.friends
       if status.user.id in self.blocks: return
       if not friend and len(status.text) > 180: return
       if not friend and '@' in status.text: return
       if status.text.startswith("RT "): return
       if self.posters.count(status.user.id) > (2 if friend else 0): return
       if len(utils.similar(status.text, self.tweets, cutoff=0.9)) > (2 if friend else 1): return

       if self.input.qsize() or self.output.qsize():
          utils.log("Twitter queues: input has %r tweets, output has %r reports" % (self.input.qsize(), self.output.qsize()))

       if not self.overwhelmed and (self.input.qsize() > 32 or self.output.qsize() > 20 or self.delay > 100):
          self.suspend()
          utils.log("WARNING: tweets delayed by %r seconds, refocusing!" % self.delay)

          with self.lock:
             Matrix(DEBUG_ROOM).send("Error", "WARNING: Refocusing tweets, %r seconds" % self.delay)

#          Timer(5, lambda: self.focus(words=["earthquake", "magnitude", "epicenter"])).start()
#          Twitter().send("Error", "🚧 Too many inbound earthquake-related tweets. My current reports may be unreliable.")

       self.total += 1

       for report in self.manager.parser(status):
          with self.lock:
             self.posters.append(status.user.id)
             self.tweets.append(status.text)

             self.valid += 1
             lag = min(1200, (When.now() - report.update).seconds)
             self.delay = self.delay*0.9 + lag*0.1

          if lag > 60:     # Commenting out as this may be counterproductive as we are ditching tweets after they've already been parsed. Let's ditch them in advance instead. But reintroducing now because apparently sometimes they get and stay too delayed anyway...
             utils.log("WARNING: tweet '%r' delayed by %r seconds (sliding window is %r)" % (status.text, lag, self.delay))
             if status.user.id not in self.friends: return

          yield report

          utils.log("Twitter report queued: %r" % status.text)

          if report.score > -1:  # was 0 but I really want to see the negative ones too as they may be swamping the positive ones
             place = "a GeoJSON location" if status.place else status.coordinates
#             locality = where.Address(where.locate(report.coords, quick=True)).tostring('short')
             pattern =  u"'{status.text}' (language: {status.lang}, from: {place}, {time}s ago, by: {status.user.screen_name})  →  "
             pattern += "'{report.keyword}' {location} in {report.region} {report.coords}, {report.mag}, {report.time}, confidence \x02{report.confidence:.3f}\x02 since {report.status}"
             pattern += ":  " + ", ".join("{d} {w:+.3f}".format(d=description, w=weight) for weight, description in sorted(report.heuristics, reverse=True))
             Matrix(DEBUG_ROOM).send("Tweet", pattern.format(status=status, report=report, place=place, time=lag, location=where.Address(where.locate(report.coords, quick=True)).tostring('long')))
          else:
             utils.log("Tweet score %r for %r" % (report.score, status.text))

       if not self.total % 8000:
          Matrix(DEBUG_ROOM).send("Stats", " - {total} tweets, {delay:.1f} average delay, {ratio:.1f}% processable".format(total=self.total, delay=self.delay, ratio=(float(self.valid)/float(self.total))*100))

          for sign in ('=', '/', '+', '-'):
             Matrix(DEBUG_ROOM).send("Heuristics", "- Heuristics ({sign} {count}): {stats}".format(sign=sign, count=Event.stats[sign], stats=", ".join("{name} ({score:.2f})".format(name=name, score=score) for score, name in Event.learned(sign=sign))))

    def on_status(self, status):
        try:
           status.text = status.extended_tweet['full_text']
        except:
           pass

        lag = (When.now() - When.fromstring(status.created_at)).seconds

        if status.text.startswith("RT "): return
        if hasattr(status, 'retweeted_status') and status.retweeted_status: return
        if hasattr(status, 'is_quote_status') and status.is_quote_status: return

        if (self.input.qsize() < 18 and self.output.qsize() < 16 and not self.overwhelmed) or status.user.id in self.friends:
           utils.log("Incoming tweet (lagging %r seconds) %s" % (lag, status.text))
           self.put((status, self))
        else:
           utils.log("Skipping tweet (lagging %r seconds) %s" % (lag, status.text))

    def on_event(self, status):
        utils.log("Unrecognized Twitter event: %s" % status)

    def on_error(self, status):
        if status in (420, 429, 406, 88):
           utils.log("WARNING! TWITTER IS RATE LIMITING US! RESPONSE CODE %s" % status)

           if not self.overwhelmed:
              self.overwhelmed = True
              try: Twitter().send("Rate limit", u"🚧 Twitter is limiting me due to excess tweets about earthquakes. I cannot provide warnings for now.")
              except: pass

           self.disconnect()
           time.sleep(600)

        return self.cleanup("Twitter error: %s" % status)

    def on_closed(self, status):
        return self.cleanup("Twitter disconnected us: status %r" % status)

    def on_exception(self, error):
        return self.cleanup("Error reading from Twitter: %s" % error)

    def disconnect(self):
        self.stream.disconnect()
        self.stream = None


class POSTReceiver(Receiver):
    type = "POST"

    @classmethod
    def accepts(cls, resource):
        return False

    def __init__(self, resource, manager):
        self.resource, self.manager = resource, manager

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({'user-agent': 'Brainstorm'})

        self.start(output=manager.input)

    def process(self):
        stopwatch = Stopwatch("Posting {payload} to {url}", long=610)
        backoff = 0

        while self.session:
            with stopwatch:
                response = self.session.post(url=self.url, data=self.payload, timeout=600)

            if stopwatch.partial < 10 or not response.ok:
                backoff = (backoff+1) * 2
                sleep(backoff)
            else:
                backoff = 0
                self.put((response.text, self))


class WebSocketReceiver(Receiver, WebSocketClient):
    type = 'WebSocket'

    @classmethod
    def accepts(cls, resource):
        return cls.urlscheme(resource) in ('ws', 'wss')

    def __init__(self, resource, manager):
        self.websocket = WebSocketClient(resource, heartbeat_freq=15) #, ssl_options={'server_hostname': requests.utils.urlparse(resource).netloc})
        self.websocket.closed = self.closed
        self.websocket.received_message = lambda message: self.put((str(message), self))

        self.resource, self.manager = resource, manager

        Thread(target=self.listen).start()

    def listen(self):
        self.websocket.connect()
        self.start(output=manager.input)
        time.sleep(30)
        self.websocket.run_forever()

    def process(self, message, origin):
        utils.log("Received from {resource}: {message}".format(resource=self.resource, message=message.replace("\n", " ")))
        for report in self.manager.parser(message): yield report

    def closed(self, code, reason=None):
        self.cleanup("WebSocket connection closed ({reason})".format(reason=reason))

    def disconnect(self):
        try: self.close_connection()
        except: pass
        try: self.sock.close()
        except: pass


class FeedParser(Rejecter):
    type = "Generic feed"
    cache = LFUCache(maxsize=512)

    def __new__(cls, data, limit=None):
        try:
           items = cls.load(data)
        except Exception as error:
           raise cls.Rejection("Not parsable as {type}: {error}".format(type=cls.type, error=error))

        results = filter(None, cls.lookup(items, limit=limit))

        if cls.type not in ['Twitter', 'BosaiEEW']:
           utils.log("{type} data identified with {count} events".format(type=cls.type, count=len(results)))

        return results

    @classmethod
    def load(cls, data): raise NotImplementedError("Abstract")

    @classmethod
    def convert(cls, item): raise NotImplementedError("Abstract")

    @classmethod
    def lookup(cls, items, limit=None):
       for index, item in enumerate(items):
          if limit and index >= limit: break

          try:
             yield cls.cache[item]
          except:
             try:
                result = cls.convert(item)
                yield result
                try: cls.cache[item] = result
                except: pass
                time.sleep(0)
             except cls.Rejection as error:
                if str(error): utils.log(error)
             except:
                utils.error("Could not convert item %r" % item)


class PatternParser(Rejecter):
    semaphore = Semaphore(4)

    @utils.cache(512)
    def __new__(cls, quake):
        with cls.semaphore:
           try:
              (entry, regex), timezone, country = earthquakes.parse(quake.text, full=True)
              utils.log("Expression '%s' parsed '%s'" % (regex, quake.text[:256]))
           except: raise cls.Rejection("No pattern could parse '%s'" % quake.text[:256])

        for number in ('mag', 'maxmag', 'lat', 'lon', 'depth'):
           if entry.get(number): entry[number] = entry[number].replace(",", ".")

        quake.time = When.fromstring(" ".join(filter(None, [entry.get('date'), entry.get('time')])), fuzzy='past', timezone=timezone) or quake.time
        quake.status = Report.Status(entry.get('status')) or quake.status or Report.Status("reported")

        if quake.time < When.now().subtract(hours=48):
           raise cls.Rejection("Obsolete time %s" % quake.time)
        elif quake.time > When.now():
           raise cls.Rejection("Future time %s" % quake.time)
        elif quake.time.second == 0:
           quake.status = Report.Status('incomplete')

        try:
           quake.coords = where.Coords(entry.get('coords') or " ".join((entry['lat'], entry['lon'])))
           quake.coords.point.altitude = -abs(float(entry.get('depth') or 10))
        except:
           if not quake.coords:
              def canonical(region): return region.replace("-", " ").replace(",", "").replace(".", "").upper()
              entry['area'] = re.sub(r'(?<!^)(?=[A-Z])', ' ', entry['area']) # add spaces to any CamelCase placename-as-hashtag

              try:
                 quake.coords = where.Coords(where.locate(", ".join(filter(None, [entry['area'], country]))).point, confidence=0.7)
                 utils.log("AREA %r, COUNTRY %r, COORDS %r" % (region, country, quake.coords))
                 region = canonical(entry['area'])
                 if region in (canonical(name) for name in where.regions.names) and canonical(where.region(quake.coords)) != region:
                    raise cls.Rejection("Coordinates %r don't match region %r in report '%r'" % (quake.coords, region, quake.text[:256]))
              except: raise cls.Rejection("Cannot get coordinates from area in %r" % quake.text[:256])

              quake.score *= 0.8
              quake.status = Report.Status('incomplete')

        if quake.coords and entry.get('intensity'):
           quake.intensity = Report.Intensity(entry['intensity'], unit="Shindo" if "Japan" in quake.region or "Taiwan" in quake.region else "Mercalli")

        try:
           quake.mag = Report.Magnitude(statistics.mean([float(entry['mag']), float(entry.get('maxmag', entry['mag']))]), entry.get('magtype'))
           quake.status = quake.status or Report.Status("detection") if entry.get('maxmag') else quake.status
        except:
           utils.error("WARNING: Messed up magnitude! %r" % entry['mag'])
           quake.mag = quake.mag or Report.Magnitude(4.5)
           quake.score *= 0.1
           quake.status = Report.Status('incomplete')


        quake.coords = quake.coords.round()  # Round so that cache use is maximized
        quake.update = When.fromstring(entry.get('update'), fuzzy='past', timezone=timezone) or quake.update
        quake.alert = Report.Severity(entry.get('alert'))
        quake.sources = filter(None, [entry.get('source')]) or quake.sources
        quake.links = filter(None, [entry.get('link')]) or quake.links
        quake.water = entry.get('water') or quake.water
        quake.victims = entry.get('victims') or quake.victims

        try: quake.water = True if len(quake.water) < 4 else quake.water
        except: pass

        utils.log("Parsed '%s': %r" % (quake.text[:256], quake))

        return quake


class P2PQuakeParser(FeedParser):
    type = "P2PQuake"
    priority = 6

    @classmethod
    def load(cls, data):
        try:
           parsed = json.loads(data)
           try:
              # The websocket service returns a single dict, while the "human-readable" v1 API returns a list
              parsed['time'], parsed['code']
              parsed = [parsed]
           except:
              parsed[0]['time'], parsed[0]['code']

           utils.log("Obtained from P2PQuake: %r" % parsed)
           print(u"Japanese time: " % parsed[0]['time'])
           return parsed
        except:
           raise cls.Rejection

    @classmethod
    def convert(cls, item):
       try: hypocenter = item['earthquake']['hypocenter']
       except:
          utils.log("Non-earthquake P2PQuake message received")
          raise cls.Rejection

       try:
          # The v1 API passes these as strings
          latitude, longitude = hypocenter['latitude'].strip("NS"), hypocenter['longitude'].strip("EW")
          depth = hypocenter['depth'].replace("km", "").replace(u"ごく浅い", "10")
       except:
          # The string conversions are not needed in the v2 streaming API
          latitude, longitude = hypocenter['latitude'], hypocenter['longitude']
          depth = hypocenter['depth']

       report = Report(where.Coords((float(latitude), float(longitude), -float(depth))))
       report.time = When.fromstring(item['earthquake']['time'], timezone="Asia/Tokyo")
       report.update = When.fromstring(item['time'], timezone="Asia/Tokyo")
       report.mag = Report.Magnitude(hypocenter['magnitude'])
       report.sources = [item['issue']['source']]

       return report


class GeoJSONParser(FeedParser):
    type = "GeoJSON"
    priority = 5

    @classmethod
    def load(cls, data):
        json = geojson.loads(data)

        if 'action' in json and 'data' in json: json['data']['action'] = json['action']

        keys = ('features', 'data', 'ultimos_sismos', 'ultimos_sismos_chile')

        for key in keys:
           try: return json[key][:]
           except: pass
           try: return [json[key]]
           except: pass

        return json

    @classmethod
    def convert(cls, item):
       def get(*paths):
          for path in paths:
             current = item
             if isinstance(path, basestring): path = [path]
             for name in path:
                 try: current = current[name]
                 except: current = None

             if current is not None: break

          return current

       try:
           try:    coords = where.Coords.fromgeojson(item['geometry']['coordinates'])
           except: coords = where.Coords.fromgeojson(item.geometry.coordinates)
           item = item.properties
       except:
           coords = where.Coords((item['latitude'], item['longitude'], item['depth']))

       coords.point.altitude = -abs(coords.point.altitude)

       quake = Report(coords)
       quake.time = When.fromstring(get(['time', 'time'], 'time', 'utc_time', 'date_time', 'origintime'))
       quake.update = When.fromstring(get(['time', 'last_update_time'], 'updated', 'lastupdate', 'modificationtime')) or quake.update
       quake.sources = (get('auth', 'sources', 'source', 'agency') or "").split(',')
       quake.mag = Report.Magnitude(get(['magnitude', 'mag'], 'magnitude', 'mag'), get('magType', 'magtype', 'magnitudetype', 'scale', ['magnitude', 'mag_type']))
       quake.alert = Report.Severity(get('alert', ['effects', 'color', 0]))
       quake.status = Report.Status(get('quality', 'action'))
       quake.water = bool(get('tsunami'))
       quake.links = [get('url', 'link')]

       return quake


class AtomParser(FeedParser):
    type = "Atom"
    priority = 3

    @classmethod
    def load(cls, data):
        parsed = feedparser.parse(data)

        # Checking for magnitude as an alternative to a proper RSS/Atom version is ad-hoc for the Iranian agency, which publishes a "generic" XML
        # with a license as its first item, so we check the second one ([1]) but in case this would fail for other regular feeds, having a version will still also work.
        if not parsed.bozo and (parsed.get('version') or parsed.entries[1]['mag']):
           return parsed.entries

        raise cls.Rejection

    @classmethod
    def convert(cls, item):
        quake = Report()

        try:
           quake.coords = quake.coords or where.Coords((item['geo_lat'], item['geo_long'], -item.get('eqDepth', 10.0)))
        except:
           try: quake.coords = quake.coords or where.Coords.fromgeojson(item.where.coordinates)
           except:
              try:
                 # Also specific additions for Iran (IRSC)
                 quake.coords = where.Coords(" ".join((item['lat'], item['long'])))
                 quake.coords.point.altitude = -abs(float(item.get('dep') or 10))
              except: pass


        try:
           value, type = item.get('mag').split(" ")
           quake.mag = Report.Magnitude(value, type)
        except:
           # Again specific to IRAN (IRSC)
           try: quake.mag = Report.Magnitude(float(item['mag']))
           except: pass


        quake.sources = filter(None, [item.get('source', {}).get('title')]) or [author.name for author in item.get('authors', [])]
        quake.alert = Report.Severity(item.get('gdacs_alertlevel'))
        quake.time = When.fromstring(item['date']) if item.get('date') else None # Iran

        for key in ('published_parsed', 'published', 'updated', 'updated_parsed', 'pubDate'):
           quake.update = When.fromstring(item.get(key), fuzzy='past') or quake.update

        quake.text = "%s: %s" % (item.get('title', "Earthquake"), utils.strip(item.get('summary', item.get('id'))))

        # Again, Iran isn't really an RSS/Atom feed with text in it, so just return the thing in their case
        try:
           return PatternParser(quake)
        except:
           if quake.mag and quake.coords and quake.time:
              utils.log("WARNING: returning raw quake %r" % quake)
              return quake


class CSVParser(FeedParser):
    type = "CSV"
    priority = -1

    @classmethod
    def load(cls, data):
        parsed = csv.DictReader(StringIO(data), dialect=csv.Sniffer().sniff(data[:4096]))

        if parsed and parsed.dialect.delimiter in (',', ';', '|', '\t'): return parsed
        else: raise cls.Rejection

    @classmethod
    def convert(cls, item):
        quake = Report()

        quake.mag = Report.Magnitude(item.get('Magnitude'), item.get('Magnitude Type'))
        quake.status = Report.Status(item.get('Status') or 'detection')
        quake.time = When.fromstring(item.get('Time') or item.get('Origin time') or item.get('Time UTC'), fuzzy='past') or When.fromstring(item.get('Datetime')).add(hours=3)
        quake.coords = where.Coords((item.get('Latitude') or item.get('Lat'), item.get('Longitude') or item.get('Lon'), -float(item.get('Depth') or item.get('Depth Km') or 10.0)))

        return quake


class QuakeMLParser(FeedParser):
    type = "QuakeML"

    router = obspy.clients.fdsn.RoutingClient("iris-federator")

    @classmethod
    @utils.cache(512)
    def map(cls, network, station):
        try:
           station = cls.router.get_stations(network=network, station=station)[0][0]
           return where.Coords((station.latitude, station.longitude))
        except:
           return None

    @classmethod
    def load(cls, data):
        data = utils.html(data)
        items = []

#        for element in ['event', 'pick']:
        for element in ['event']:
           items += data.findAll(element)

        if items: return items
        else: raise cls.Rejection

    @classmethod
    def convert(cls, item):
        def get(item, cast=str):
            try: return cast(item.value.string or item.text.string)
            except: pass
            try: return cast(item.string)
            except: return None

        report = Report()

        if item.name == 'pick':
           utils.log("Handling pick %r" % str(item)[:512])

           try: t0 = get(item.find('ee:t0'), float)
           except: raise cls.Rejection("Bad pick")

           network = item.waveformid.get('networkcode') or get(item.waveformid.find('networkcode'))
           station = item.waveformid.get('stationcode') or get(item.waveformid.find('stationcode'))

           try: report.coords = cls.map(network, station)
           except: raise cls.Rejection("Cannot locate station %r %r" % (network, station))

           report.score = 0.5
           report.status = Report.Status('guessed')
           report.mag = Report.Magnitude(clip(0.80*math.log10(t0)**2+1.7*math.log10(t0)-0.87, 3.5, 6.5), "Md")
           report.time = get(item.time, When.fromstring)
           report.sources = [network]

           utils.log("Gotten pick from {report.coords} at {report.time}, {report.mag}".format(report=report))

        elif item.name == 'event':
           utils.log("Handling event %r" % str(item)[:256])

           if 0 < get(item.magnitude.stationcount, float) < 4: report.status = Report.Status('guessed')

           report.coords = where.Coords((get(item.latitude, float), get(item.longitude, float), -abs(get(item.depth, float)) / 1000))
           report.mag = Report.Magnitude(get(item.magnitude.mag, float), get(item.magnitude.type))
           report.time = get(item.origin.time, When.fromstring) or get(item.time, When.fromstring)
           report.update = get(item.creationinfo.creationtime, When.fromstring) or report.update
           report.sources = [get(item.creationinfo.agencyid) or get(item.creationinfo.author)]

           try:
              mag = item.magnitude.mag
              report.score = max(0.1, report.score - 1.5/get(item.magnitude.stationcount, float))
              report.score = max(0.1, report.score - (get(mag.upperuncertainty, float) - get(mag.loweruncertainty, float)))
           except:
              utils.error("No magnitude uncertainty range provided in %r" % report)

        else:
           raise cls.Rejection("Wrong element type")

        return report


class ObsPyParser(FeedParser):
   type = "ObsPy"
   priority = 2

   @classmethod
   def load(cls, data):
      try: return data.events
      except: return obspy.read_events(StringIO(data)).events

   @classmethod
   def convert(cls, event):
      origin = event.origins[0]
      magnitude = event.magnitudes[0]
      info = event.creation_info or origin.creation_info or magnitude.creation_info

      def agency(info):
         try: return info.author or info.agency_id or info.agency_uri.replace("smi:smi-registry/organization/", "")
         except: return None

      quake = Report(where.Coords((origin.latitude, origin.longitude, -abs((origin.depth or 10000.0)/1000.0))))
      quake.mag = Report.Magnitude(magnitude.mag, magnitude.magnitude_type)
      quake.time = When.from_datetime(origin.time.datetime)
      quake.update = When.from_datetime(info.creation_time.datetime) if info and info.creation_time else quake.update
      quake.sources = filter(None, [agency(info)]) or quake.sources

      quake.status = Report.Status(origin.evaluation_status or origin.evaluation_mode or magnitude.evaluation_status or magnitude.evaluation_mode)

      return quake
    

class TweetBag(object):
   def __init__(self, size=1024, window=600):
      self.size = size
      self.window = window

      self.statistics = LFUCache(maxsize=self.size)

   def add(self, status):
      for word in status.text.split():
         self.statistics.setdefault(word, TTLCache(maxsize=self.size, ttl=self.window, missing=False))
         self.statistics[word].setdefault(status, True)

   def locate(self, statuses):
      return where.Coords.center(Twitter.locate(status) for status in statuses if status.place or status.coordinates)

   def top(self):
      def sorter((word, count, coords)): return float(count) / (clip(coords.radius, 1.0, 500.0) if coords else 500.0)

      return sorted([(word, len(statuses), self.locate(statuses)) for word, statuses in self.statistics.items()], key=sorter, reverse=True)


# Note the v1 Twitter streaming API is no longer available, so this code will not really work anymore.
# It could be ported to the v2 streaming API, but it's now only available to paying user for a very high price.
# Be aware, and thank the new Twitter owner for this.

class TwitterParser(FeedParser):
    type = 'Twitter'
    priority = 10

    tweetbag = utils.Locking(TweetBag(size=256, window=300))
    scores = LFUCache(maxsize=1024)
    keywords = TTLCache(maxsize=512, ttl=20)
    delayed = False
    terms = Counter()

    @classmethod
    def load(cls, data):
        if not isinstance(data, tweepy.models.Status): raise cls.Rejection("Not a Twitter status")

        return [data]

    @classmethod
    def convert(cls, status):
        def density(text):
           return len(text.encode('utf-16').encode('bz2'))

        utils.log("Parsing tweet: %s (%s)" % (status.text.replace("\n", " "), status.user.screen_name))

        user = Twitter(status.user)
        text = status.text.replace("\n", " ")
        languages = {status.lang, user.language} # user.language is deprecated and set to NULL apparently, so no use anymore. tweet.py will always return 'en'

        report = Report()
        report.text = text.replace("#", "")
        report.user = user
        report.links = ['https://twitter.com/%s/status/%s' % (status.user.screen_name, status.id)]


        try:    report.update = When.fromstring(status.created_at)
        except: pass

        try:    report.update = When.from_datetime(status.created_at)
        except: pass

        if user in cls.alerters:
           utils.log("Tweet from alerter: %r" % text)

           report.status = Report.Status("reported")
           report.sources = [status.user.screen_name]

           try:
              report.time = report.update.subtract(seconds=5)
              # This has caused problems with "Earth" (@myearthquakeapp's profile location) ending up being used in a report.
              # Must look at locate() and coords() function in tweet.py better to figure out why it's not being caught and how to catch it.
              #report.coords = Twitter.locate(status)
              report = PatternParser(report)
              return report
           except Exception as error:
              utils.log("WARNING: Problem parsing Twitter alerter (%r)" % error)
              if not report: return
           finally:
              try:
                 utils.log("STREAM Twitter alerter {user} reported: {tweet}  ->  {report}".format(user=user, tweet=text, report=report))
                 cls.evaluate(status.user.screen_name, +1.0)
              except:
                 utils.log("STREAM Twitter alerter {user} reported unparsable: {tweet}".format(user=user, tweet=text))
                 cls.evaluate(status.user.screen_name, -1.0)

              if not report: return

           report.time = report.update.subtract(seconds=density(text)*0.3)
           report.status = Report.Status("guessed")

           conditions = [
              'http' not in text,
              u'震度0' not in text,
              not hasattr(status, 'retweeted_status') or not status.retweeted_status,
              not hasattr(status, 'is_quote_status') or not status.is_quote_status,
              density(text) < 120,
           ]

           if not all(conditions):
              for index, condition in enumerate(conditions): return
#           else: cls.tweetbag.add(status)

        if "@" in text:
           utils.log("Fake Reply tweet by %r (%r): %s (languages: %s)" % (status.user.screen_name, status.user.id, text, languages))
           return
        elif any(keywords.contained(keyword, text, languages) for keyword in ["earthquake", "alert", "earthquake warning"]):
           utils.log("Relevant tweet by %r (%r): %s" % (status.user.screen_name, status.user.id, text))
           report.keywords = [keywords.contained("earthquake", text, languages) or keywords.contained("alert", text, languages) or keywords.contained("earthquake warning", text, languages)]
        elif any(keywords.contained(keyword, text) for keyword in ["earthquake", "alert", "earthquake warning"]):
           utils.log("Mismatched tweet by %r (%r): %s (languages: %s)" % (status.user.screen_name, status.user.id, text, languages))
           cls.evaluate(status.user.screen_name, -0.05)
           return
        else:
           utils.log("Reply tweet by %r (%r): %s (languages: %s)" % (status.user.screen_name, status.user.id, text, languages))

        mapping = {'weak': 4.5, 'strong': 6.0, 'very strong': 6.5, 'destroyed': 7.0}
        magnitudes = [mapping[keyword] for keyword in mapping if keywords.contained(keyword, text, languages)]
        report.mag = Report.Magnitude((max(magnitudes) if magnitudes else 5.0), "(just guessing)")

        if keywords.contained("alert", text, languages) and not keywords.contained("earthquake", text, languages):   # then it's not an earthquake
           # We use a smaller arbitrary magnitude to distinguish between multiple air raids in multiple cities instead of being treated them as one blob
           report.mag = Report.Magnitude(3.5, "(arbitrarily assigned)")

        heuristics = [
           (density(text) < 75, "very brief text", 0.16),
           (density(text) < 90, "brief text", 0.08),
           (density(text) > 100, "long text", -0.08),
           (any('QUESTION' in unicodedata.name(character, "unknown") for character in text), "question", -0.05),
           (any('EXCLAMATION' in unicodedata.name(character, "unknown") for character in text), "exclamation", +0.05),
           (sum('QUESTION' in unicodedata.name(character, "unknown") for character in text) > 1, "double question", +0.08),
           (sum('EXCLAMATION' in unicodedata.name(character, "unknown") for character in text) > 1, "double exclamation", +0.03),
           ((u"..." in text) or (u"…" in text), "ellipsis", -0.02),
           (u"@"  in text, "usernames", -0.1),
           (sum(character == "#" for character in text) > 1, "multiple hashtags", +0.03),
           (any("#"+keyword in text for keyword in keywords.get("earthquake")+keywords.get("alert")), "relevant hashtag", +0.05),
           (density(text) < 75 and any("#"+keyword in text for keyword in keywords.get("earthquake")+keywords.get("alert")), "short with hashtag", +0.05),
           (any(alerter.nickname in text for alerter in cls.alerters), "agency usernames", -0.05),
           ("FULL STOP" in unicodedata.name(text[-1], "unknown"), "final period", -0.04),
           (sum(unicodedata.category(character).startswith("L") for character in text) < len(text)*0.4, "little content", -0.1),
           (sum(unicodedata.category(character) == "Lu" for character in text) > len(text)*0.8, "caps lock", 0.25),
           (all(unicodedata.category(character) != 'Zs' for character in text), "no spaces", +0.1),
           (any(unicodedata.category(character) == 'Nd' for character in text), "numbers", -0.03),
           (any(unicodedata.category(character) == 'So' for character in text), "symbols", -0.01),
           (any(unicodedata.category(character) == 'Cn' for character in text), "emoji", -0.1),
#           (re.search(u'[😟😢😧😭😲😐😑😮😔😣😖😬😔😓😱😨😰😫😬😳🥺🔴🛑📢⚡💥️🚨⚠]', text, re.UNICODE), "worried emoji", +0.13),  # was +0.1 but increased for Ukraine
           (re.search(u'[😟😢😧😭😲😐😑😮😔😣😖😬😔😓😱😨😰😫😬😳🥺🔴🛑📢⚡🚨⚠]', text, re.UNICODE), "worried emoji", +0.13),  # Ukraine no longer triggers much, but instead there are some false positives
           (u"震度" in text, "shindo", +0.2),
           (u"震度0" in text or u"震度1" in text, "low shindo", -0.2),
           (u"地震情報" in text or u"強震モニタ速報" in text, "Japanese early warning", +0.2),
           (all(not keywords.contained(keyword, text, languages) for keyword in ["earthquake", "alert", "earthquake warning"]), "no keyword", -0.3),
           (keywords.contained("strong", text, languages) or keywords.contained("very strong", text, languages), "intensifier", +0.15),
           (keywords.contained("haha", text, languages), "laughter", -0.08),
           (keywords.contained("simulation", text, languages), "simulation", -0.5),
           (user in cls.alerters, "alerter account", +0.01),
           (keywords.contained("alert", text, languages) and not keywords.contained("earthquake", text, languages), "other event", +0.02),   #temporary test
           (any(keyword.lower() in text.lower() for keyword in keywords.spam), "football player", -0.3),
        ]

        report.heuristics = [(weight, description) for rule, description, weight in heuristics if rule]

        if cls.keywords.get(status.lang) and sum(weight for weight, description in report.heuristics) < 0:
           utils.log("Discarding tweet %r" % text)
           return

        for keyword in ["earthquake", "alert", "earthquake warning"]:
           if keywords.contained(keyword, text, languages): cls.terms.update([keywords.contained(keyword, text, languages)])

        lag = (When.now() - report.update).seconds
        if cls.delayed or lag > 40:
           utils.log("WARNING: Skipping location processing for tweet by {user} (delayed? {delayed}, lag: {lag}): {tweet}".format(user=user, tweet=text, delayed=cls.delayed, lag=lag))
        else:
           report.coords = report.coords or Twitter.locate(status) or user.coords

        if report.coords and status.lang not in {'en', 'es'} and keywords.contained("earthquake", text, languages):
           cls.keywords[status.lang] = where.Coords(report.coords, confidence=report.coords.confidence*0.5)

        if not report.coords and keywords.contained("earthquake", text, languages):
           # Don't give this a negative weight because it could make the entire report negative, ... negating the usefulness of caching.
           # But make the whole score just lower; maybe it needs to be even lower than half, but I'll have to tune that.
           report.heuristics = [(weight*0.6, description) for weight, description in report.heuristics]
           report.coords = cls.keywords.get(status.lang)
           # Don't necessarily use language-cached coordinates or we may overzealously catch a big city by mistake just because they are talking about the events
           if report.coords and random.random() > 0.5: utils.log("Recalling coordinates %r from %r" % (report.coords, status.lang))

        if not report.coords:
           cls.evaluate(status.user.screen_name, -0.1)
           return

        try:
           spoken = langcodes.country(where.Address(where.locate(report.coords, quick=True)).countrycode)
           if status.lang not in spoken:
              try: candidate = engines.LanguageIdentifier(text).process().merge().output[0][0]
              except: candidate = status.lang
              if candidate not in spoken:
                 utils.log("Language mismatch: %r, expected %r for %r" % (status.lang, spoken, text))
                 report.heuristics.append((-0.15 if candidate in ['en', 'eng'] else -0.3, "language mismatch"))
                 try: del cls.keywords[status.lang]
                 except: utils.error("Could not delete keyword")
        except:
           utils.error("Language error %r: %s" % (status.lang, text))
           report.heuristics.append((-0.05, "language error"))

        report.score = sum(weight for weight, description in report.heuristics)
        report.score *= report.coords.confidence
        report.coords = report.coords.round()

        utils.log("Tweet '%s' (%.3f dense, in '%s', from '%s') by %r:   %r" % (text, density(text), status.lang, status.coordinates or status.place, user.nickname, report))
        utils.log("Scores: " + ", ".join("%s (%s)" % (description, weight) for weight, description in report.heuristics) + " = %s" % report.score)

        cls.evaluate(status.user.screen_name, report.score)

        return report

    @classmethod
    def evaluate(cls, id, score):
        cls.scores.setdefault(id, 0.0)
        cls.scores[id] += score


class EventDatabase(object):
    def __init__(self, name, maxage=3600*12):
        self.timestamp = time.time() - maxage
        self.lock = RLock()

        for flag in ('c', 'n'):
           try:
              with self.lock:
                 self.events = shelve.open(name, flag, writeback=False)
                 for event in dict(self.events):
                    if self.events[event] < self.timestamp:
                       del self.events[event]
                 break

           except:
              try: self.events.close()
              except: pass

        else:
           raise RuntimeError("Cannot open database")

    def add(self, event):
        with self.lock:
           self.events[repr(event)] = time.time()
           self.events.sync()

    def __contains__(self, event):
        with self.lock:
           try:
              if repr(event) in self.events:
                 return True
              else:
                 self.add(event)
                 return False
           except:
              utils.error("Database error")
              os._exit(os.EX_SOFTWARE)


class FeedManager(Worker):
    threshold, precision = 2.5, 1000
    recent, trend = TTLCache(maxsize=256, ttl=100), TTLCache(maxsize=2048, ttl=1000)

    recent[None], trend[None] = 1.0, 1.0

    def __init__(self, parser, history=None):
        super(FeedManager, self).__init__()
        self.parser = parser
        self.receivers = set()
        self.history = history or deque(maxlen=64)
        self.dejavu = EventDatabase("dejavu.db")

        self.start()
        self.started = When.now()

        poller = Worker(processor=self.poll)
        poller.start(input=poller.ticker(seconds=30))

    def poll(self, tick, origin):
        for receiver in list(self.receivers):
           if not receiver.running:
              utils.log("Receiver {receiver} for {receiver.resource} died, restarting".format(receiver=receiver))
              self.receivers.remove(receiver)
              self.add(receiver.resource)
              del receiver
              yield

    def add(self, resource):
        utils.log("Adding resource %s" % resource)
        self.receivers.add(Dispatcher(Receiver)(resource, self))

    def remove(self, resource):
        self.receivers.remove(resource)

    slider = 0.2

    def process(self, report, origin):
        def adjust(report):
           self.recent[report] = self.trend[report] = True

           factor = float(len(self.recent)*self.trend.ttl) / float(len(self.trend)*self.recent.ttl)
           factor = min(1.0, 1.0 / factor) if None in self.trend else factor
           factor = clip(factor, 0.7, 1.5)

           self.slider = self.slider*0.95 + factor*0.05

           utils.log("%d reports / %d minutes, vs average of %d (factor %.3f, slider %.3f, inverted: %s)" % (len(self.recent), self.recent.ttl / 60.0, len(self.trend) / float(self.trend.ttl/self.recent.ttl), factor, self.slider, None in self.trend))

           return self.slider

        if report.posted < When.now().subtract(hours=12): return
        if report.posted < self.started: return
        if report.mag < self.threshold: return
        if report.coords.radius > self.precision: return
        if report in self.dejavu: return

        if report.confidence < 0.4: report.score *= adjust(report)

        notice = Notice(report, provider=origin)

        if notice.confidence > 0.5 and notice not in self.history:
           self.history.append(notice)
           if notice.warners:
              utils.log("CONFIRMATION: {count} witness with {confidence} confidence, {score} score in region {region} at {time}".format(count=len(notice.warners), confidence=sum(witness.confidence for witness in notice.warners), score=sum(witness.score for witness in notice.warners), region=notice.region, time=notice.time))

        utils.log("{notice.provider} spawned {notice.priority}-priority event with {count} reports: {notice}".format(notice=notice, count=len(notice)))

    def subscribe(self, threshold=0.95, name=None):
        subscriber = self.Subscriber(self, name=name)
        subscriber.threshold = threshold
        self.subscribers.add(subscriber)
        return subscriber

    def focus(self, type, **kwargs):
        for receiver in self.receivers:
           if receiver.type == type: receiver.focus(**kwargs)


class Report(object):
    slowmodel = obspy.taup.TauPyModel(cache=OrderedDict())
    fastmodel = obspy.taup.TauPyModel(cache=OrderedDict())

    @total_ordering
    class Status(object):
        table = [
           (['rejected', 'deleted', 'invalid'], 0.0),
           (['guessed', 'presumed', 'crowdsourced'], 0.1),
           (['incomplete', 'partial', 'caution', '1'], 0.4),
           (['a', 'automatic', 'auto', 'detection', 'detected', 'detectado', 'good', 'stima provvisoria', 'flash', '2'], 0.6),
           (['preliminary', 'prelim', 'prelim.', 'preliminar', 'provisional', 'reported', 'best', 'create', '3', u'速報'], 0.7),
           (['confirmed', 'c', 'update', 'updated', 'detailed', u'終', '4'], 0.9),
           (['manual', 'm', 'reviewed', 'rev.', 'dati rivisti', '5'], 0.95),
           (['revised', u'revisión', 'revisado'], 1.0),
           (['final'], 1.0),
        ]

        def __init__(self, status):
           if status: status = status.lower()

           for synonyms, confidence in self.table:
              if status in synonyms:
                 self.description, self.confidence = synonyms[0], confidence
                 return

           self.description, self.confidence = "unknown", 0.8

        def __lt__(self, other):
           return self.confidence < other.confidence

        def __eq__(self, other):
           return self.confidence == other.confidence

        def __str__(self):
           return str(self.description)

        def __repr__(self):
           return "'{status.description}'~{status.confidence}".format(status=self)

    class Magnitude(float):
        def __new__(cls, magnitude, unit=None):
           value = float(str(magnitude).replace(",", ".").strip("M+~"))

           if value > 9.5: utils.error("WARNING: Magnitude %r is implausible!" % value)
           return float.__new__(cls, value) if value < 9.7 else float.__new__(cls, 3.0)

        def __init__(self, magnitude, unit=None):
           self.unit = "M" if not unit else ("M" + unit) if not unit.capitalize().startswith('M') and len(unit) < 4 else unit

        def __repr__(self): return "{mag:.1f} {unit}".format(mag=float(self), unit=self.unit.capitalize().strip())

        def __format__(self, style):
           if style == 'fuzzy':
              rounded = int(round(float(self)))
              sign = "+" if float(self) > rounded else "-" if float(self) < rounded else "~"
              return "M{number}{sign} estimated".format(number=rounded, sign=sign)
           elif style == 'early':
              strength = "very strong" if float(self) > 5.80 else "strong" if float(self) > 5.02 else "weak" if float(self) < 4.98 else "moderate"
              return "Maybe {strength}".format(strength=strength)
           else:
              return "{mag:.1f} {unit}".format(mag=float(self), unit=self.unit.capitalize().strip())

        __unicode__ = __str__ = __repr__

    class Intensity(float):
       map = {
          0: {'Shindo': [u"0", u"０"]},
          1: {'Shindo': [u"1", u"１"], 'Mercalli': [u"I", u"1"], 'Liedu': [u"I", u"1"]},
          2: {'Shindo': [u"2", u"２"], 'Mercalli': [u"II", u"2"], 'Liedu': [u"II", u"2"]},
          3: {'Shindo': [u"3", u"３"], 'Mercalli': [u"III", u"3"], 'Liedu': [u"III", u"3"]},
          4: {'Shindo': [u"4", u"４"], 'Mercalli': [u"IV", u"4"], 'Liedu': [u"IV", u"4"]},
          4.5: {'Shindo': [u"5-", u"5弱", u"５弱"]},
          5: {'Shindo': [u"5", u"５"], 'Mercalli': [u"V", u"5"], 'Liedu': [u"V", u"5"]},
          5.4: {'Shindo': [u"5+", u"5強", u"５強"]},
          5.5: {'Shindo': [u"6-", u"6弱", u"６弱"]},
          6: {'Mercalli': [u"VI", u"6"], 'Liedu': [u"VI", u"6"]},
          6.4: {'Shindo': [u"6+", u"6強", u"６強"]},
          7: {'Shindo': [u"7", u"７"], 'Mercalli': [u"VII", u"7"], 'Liedu': [u"VII", u"7"]},
          8: {'Mercalli': [u"VIII", u"8"], 'Liedu': [u"VIII", u"8"]},
          9: {'Mercalli': [u"IX", u"9"], 'Liedu': [u"IX", u"9"]},
          10: {'Mercalli': [u"X", u"10"], 'Liedu': [u"X", u"10"]},
          11: {'Mercalli': [u"XI", u"11"], 'Liedu': [u"XI", u"11"]},
          12: {'Mercalli': [u"XII", u"12"], 'Liedu': [u"XII", u"12"]},
       }

       def __new__(cls, intensity, unit=None):
          for number in cls.map:
             for scale in cls.map[number]:
                if not unit or scale.lower() == unit.lower():
                   if any(candidate == intensity for candidate in cls.map[number][scale]):
                      return float.__new__(cls, float(number))

       def __init__(self, intensity, unit=None):
          self.unit = "Mercalli" if not unit else unit.capitalize().strip()

       def __repr__(self): return "{unit} ({intensity})".format(intensity=float(self), unit=self.unit)

       def __format__(self, style): return u"{unit} {intensity}".format(intensity=self.map[float(self)][self.unit][0], unit=self.unit)

       __unicode__ = __str__ = __repr__


    class Severity(int):
        values = {'green': 1, 'yellow': 2, 'orange': 3, 'red': 4}
        durations = {'green': 120, 'yellow': 180, 'orange': 240, 'red': 300}
        colors = {'green': "03", 'yellow': "08", 'orange': "07", 'red': "04"}

        def __new__(cls, alert): return int.__new__(cls, Report.Severity.values.get((str(alert) or "").lower(), 0))
        def __init__(self, alert, unit=None): self.description = str(alert)
        def __repr__(self): return self.description
        def __eq__(self, other): return int(self) == int(other)
        def __gt__(self, other): return int(self) > int(other)
        def __lt__(self, other): return int(self) < int(other)

        @property
        def duration(self):
           return self.durations.get(self.description, 60)

        def __format__(self, style):
           string = str(self).capitalize() if 'u' in style else str(self)
           return ("\x03{color}{string}\x03" if 'c' in style else "{string}").format(color=self.colors.get(self.description, u"01"), string=string)

        __unicode__ = __str__ = __repr__

    def __init__(self, coords=None, time=None, mag=None, intensity=None, region=None, alert=None, text="", keyword=None, score=1.0):
        self.confirmed = False
        self.heuristics = []

        self.time = time
        self.update = When.now().subtract(seconds=60)
        self.update = time if time and time > self.update else self.update
        self.mag = Report.Magnitude(mag) if mag else None
        self.intensity = Report.Intensity(intensity) if intensity else None
        self.coords = coords
        self.alert = Report.Severity(alert)
        self.water = None
        self.victims = None
        self.sources = []
        self.links = []
        self.score = score
        self.children = [self]
        self.status = Report.Status("confirmed")
        self.user = None
        self.text = text
        self.keywords = [keyword] if keyword else []


    def __nonzero__(self):
        return bool(self.coords and self.time and self.mag)

    @property
    def keyword(self):
       return self.keywords[0] if self.keywords else None

    @property
    def radius(self):
        # With the dubious help of ChatGPT
        return min(800.0, math.exp(0.666*self.mag + 1.2) * (self.depth or 10.0)**0.2)

    @property
    def confidence(self):
        return clip(self.score * self.status.confidence, 0.00005, 1.0)

    @property
    def posted(self):
        return self.update or self.time

    @property
    def priority(self):
        #return self.confidence * self.mag
        return 30.0 / clip(When.now().epoch - self.time.epoch, 1, 3600) * self.confidence * self.mag

    @property
    def official(self):
        return self.status >= Report.Status('preliminary') and self.coords.radius < 300

    @property
    def crowdsourced(self):
        return self.status <= Report.Status('guessed') and self.text and self.score > 0

    @property
    def depth(self):
        if self.coords.point.altitude > 0: utils.log("WARNING: positive altitude for %r" % self)
        return abs(self.coords.point.altitude) or 10.0

    @property
    def roughcoords(self):
       return self.coords.round()

    @property
    @utils.cache(16)
    def region(self):
       return where.region(self.coords.round()).title() if self.coords else None

    @property
    @utils.cache(16)
    def location(self):
       return where.locate(self.coords.round())

    @utils.cache(16)
    def place(self, style='long'):
        if self.water is None:
           try: self.water = where.sea(self.coords.round())
           except: pass

        if self.water: return self.region

        try: address = where.Address(self.location).tostring(style) or self.region
        except: address = self.region

        # If the best resolution we get is a country name, use the FE region instead
        return self.region if countrynames.to_code(address) else address

    @property
    @utils.cache(16)
    @profile
    def tsunami(self):
        if self.water is None:
           try: self.water = where.sea(self.coords.round())
           except: pass

        if type(self.water) is not bool and self.water:
           return ' '.join(self.water.split()).title().replace("...", ",")
        elif self.mag > 7.3 and self.depth < 60:
           return self.region if self.water else False
        else:
           return False

    @classmethod
    @utils.cache(64)
    @profile
    def travel(cls, depth, distance, urgent=False):
       phases = ['S', 's']

       model = cls.fastmodel if urgent else cls.slowmodel
       depth, distance = round(depth, -1), round(distance)
       return [arrival.time for arrival in model.get_travel_times(depth, obspy.geodetics.kilometer2degrees(distance), phases)]

    @utils.cache(64)
    @profile
    def arrival(self, location=None, radius=None):
       if location:
          return min(self.travel(self.depth, self.coords - location, urgent=True))
       elif radius:
          return max(self.travel(self.depth, radius, urgent=False))

    def __len__(self):
        return len(self.children)

    def __repr__(self):
        return u"%s(coords=%r, mag=%s, time=%s, region=%r, score=%.4f, confidence=%.4f, sources=%r, alert=%r, status=%r, keywords=%s, reports=%r)" % (
           type(self).__name__, self.coords, self.mag, self.time, self.region, self.score, self.confidence, list(set(self.sources))[:4], self.alert, self.status, self.keywords, len(self.children)
        )

#((10000.0*self.mag + 22357.0)/16265.0)
#    @property
#    def radius(self):
#       # M = 1.6265 ln(30) - 2.2357
#       #mag = self.mag or 4.0 # 1.06*math.log(self.radius) + 0.16 if self.radius else self.mag
#       return math.e**(4.0/163.0) * (25*self.mag + 56)

    @utils.cache(16)
    def __eq__(self, other):
        if repr(self) == repr(other): return True

        if not self.mag or not other.mag: return False
        if abs(self.mag - other.mag) > 2.5: return False
        if abs(self.time.epoch - other.time.epoch) > 300: return False
        if self.coords - other.coords > 600: return False

        confidence = min(self.confidence, other.confidence)
        depth = round(max(self.depth, other.depth), -1)
        distance = round(self.coords - other.coords, -1)
        travel = max(Event.travel(depth, distance) or [0])

        if abs(self.time.epoch - other.time.epoch) > clip(travel/confidence, 60, 300): return False
        if self.coords - other.coords > clip((self.radius + other.radius)/max(0.5, confidence), 100, 500): return False

        return True

    def __lt__(self, other):
        return self.priority > other.priority

#    def __hash__(self):
#       return hash((self.coords, self.mag, self.time, self.score, self.alert))


class Event(Report):
   maxreports = 128
   history = deque(maxlen=maxreports)
   lock = Lock()
   stats = {}

   def __init__(self, report):
      super(Event, self).__init__()

      self.children = deque(maxlen=128)
      self.time = report.time
      self.timestamp = When.now().epoch

      if self.time > When.now(): raise RuntimeError("Event %r is in the future" % report)

      with self.lock:
         for previous in self.history:
            if not previous: continue

            if report == previous or report in previous.children:
               self.children.extend(previous.children)
               self.time = min(self.time, previous.time)
               self.history.remove(previous)
               break

         self.children.appendleft(report)
         self.history.append(self)

      if self.official:
         self.children = deque((child for child in self.children if child in self.witnesses or child.confidence > 0.2), maxlen=self.maxreports)
      elif len(self.children) > 1 and self.children[-1].score < 0:
         utils.log("Killing bad child {bad} from {good}".format(bad=self.children[-1], good=self))
         self.children.pop()

      assert(len(self.children) > 0)
      assert(len(self.best) > 0)

      self.time = self.best[0].time if self.official else self.time
      self.score = sum(child.score if child.status > Report.Status('invalid') else -1.0 for child in self.best)
      self.coords = where.Coords.center((child.coords, child.priority) for child in self.best).round()
      self.mag = Report.Magnitude(sum(child.mag * child.confidence for child in self.best) / self.confidence)
      self.mag.unit = self.best[0].mag.unit
      self.intensity = max([child.intensity for child in self.children if child.intensity] or [None])
      self.update = max(child.update for child in self.children)
      self.water = filter(None, set(child.water for child in self.children))
      self.water = ' '.join(entry for entry in self.water if isinstance(entry, basestring)) or any(self.water)
      self.alert = max(child.alert for child in self.best)
      self.links = filter(None, chain(*(child.links for child in self.best if child.official)))
      self.sources = filter(None, chain(*(child.sources for child in self.best)))
      self.status = self.best[0].status
      self.keywords = [keyword for child in self.witnesses for keyword in child.keywords]
      utils.log("Keywords now: %r" % self.keywords)
#      self.keywords = [child.keyword for child in self.witnesses if child.keyword]
      self.keywords = sorted(set(self.keywords), key=self.keywords.count, reverse=True) if self.keywords else []
      utils.log("Keywords now after consolidating: %r" % self.keywords)


   def learn(self, report, score):
      if not report.heuristics: return
      if report.status > Report.Status("reported"): return

      sign = "+" if self.official else "-"
      score *= 1.0 if sign == "+" else -1.0
      self.stats[sign] = self.stats.get(sign, 0) + abs(score)

      for weight, name in report.heuristics:
         self.stats[name+sign] = self.stats.get(name+sign, 0) + score
         self.stats["total"+sign] = self.stats.get("total"+sign, 0) + score

      report.heuristics = []
      self.stats["/"] = self.stats["+"] / self.stats["-"]

   @classmethod
   def model(cls, tick, origin):
      for event in list(cls.history):
         if event.official or (not event.timely and event.elapsed(30)):
            if not event.timely:
               with cls.lock: cls.history.remove(event)

            if len(event.children) < 4:
               continue

            for child in event.warners:
               event.learn(child, score=1.0)

            for child in event.witnesses:
               event.learn(child, score=0.1)

            event.stats['='] = event.stats.get('=', 0) + 1

      cls.stats.sync()
      yield

   @classmethod
   @profile
   def learned(cls, heuristics=[], sign="="):
      def individual(name, sign='='):
         positive = (cls.stats.get(name+'+', 0)/cls.stats['+'] if sign != '-' else 0)
         negative = (cls.stats.get(name+'-', 0)/cls.stats['-'] if sign != '+' else 0)

         return positive + negative if sign != '/' else abs((positive / negative) if negative else 999)

      heuristics = heuristics or cls.stats

      return sorted({(individual(name[:-1], sign), name[:-1]) for name in heuristics if len(name) > 1}, reverse=False if sign == '-' else True)

   @property
   @utils.cache(16)
   def confidence(self):
      return sum(child.confidence for child in self.best)

   @property
   @utils.cache(16)
   def best(self):
      children = sorted(self.children, key=lambda child: child.confidence, reverse=True)
      return [child for index, child in enumerate(children) if sum(child.confidence for child in children[:index]) < 1.0]

   @property
   @utils.cache(16)
   def witnesses(self):
      return sorted(child for child in self.children if child.crowdsourced and child.update < self.time.add(minutes=10))

   @property
   @utils.cache(16)
   def warners(self):
      return sorted(child for child in self.witnesses if child.update < self.time.add(seconds=self.arrival(radius=self.radius)))

   @property
   @utils.cache(16)
   def official(self):
      return filter(lambda child: child.official, self.children)

   @property
   @utils.cache(16)
   def tsunami(self):
      return " ".join(child.tsunami for child in self.children if child.tsunami)

   @property
   @utils.cache(16)
   def radius(self):
      weight = min(0.9, len(self.witnesses)*0.03)
      mean = sum(report.radius*report.confidence for report in self.best) / self.confidence
      points = [self.coords - witness.coords for witness in self.witnesses]
      felt = statistics.mean(points) + statistics.stdev(points) if len(points) > 1 else mean

      return min(800.0, felt*weight + mean*(1-weight))

   @property
   def title(self):
      return (self.children + filter(lambda child: child.official, self.children))[-1]


class Statement(object):
   bold = "\x02%s\x02"

   def __init__(self, style='machine', highlight=None, language='en', **data):
      self.style = style
      self.highlight = highlight
      self.text = []
      self.language = language
      self.data = data

   def __unicode__(self):
      return " ".join(filter(None, self.text))

   __str__ = __unicode__

   def format(self, formatting, **data):
      data.update(self.data)
      formatting = data.pop(self.style, formatting)
      formatted = unicode(formatting).format(**data) if (formatting and filter(None, data)) else None
      return unicode((self.bold % formatted) if self.highlight in data else formatted) if formatted else None

   def append(self, formatting, **data):
      self.text.append(self.format(formatting, **data))

   def prepend(self, formatting, **data):
      self.text.insert(0, self.format(formatting, **data))


class Notice(Event):
   red = "\x02\x0304%s\x03\x02"
   italic = "\x1d%s\x1d"
   webcams_url = "https://api.windy.com/api/webcams/v2/list/nearby=%s,%s,%s/orderby=distance/property=live?show=webcams:url"

   icons = {
      'green': u"✅",
      'yellow': u"🔸",
      'orange': u"🔶",
      'red': u"🔴",
      'alert': u'🚥',
      'tsunami': u"🌊",
      'epicenter': u"🞊",
      'stronger': u'📈', # u"🔺",
      'worse': u'📈', # u"🔺",
      'weaker': u'📉', # u"⯆",
      'depth': u"⇳",
      'frequency': u'⚠️',
      'magnitude': u'⭕',
      'population': u'🏠',
      'felt': u'💬',
      'tentative': u'❔',
      'victims': u'🕯️',
      'emergency': u'🚨',
#      'official': u'❕',
   }

   def __init__(self, report, provider=None):
      super(Notice, self).__init__(report)
      self.provider = provider
      self.tag = self.region

      # Don't consider negative scores for non-earthquake tweets, as they may be foreign tweets getting penalized but being valid reports
      # This is not great to have here as Event normally does this, but Event doesn't know about categories...
      # Actually DO consider them now, and remove this for now, because too many alerts are false positive from football matches. Sigh
#      if self.category != "earthquake": self.score = sum(child.score for child in self.best if child.score > 0)

   @property
   @utils.cache(16)
   def languages(self):
      try:
         result = where.languages(self.region) or langcodes.country(where.Address(where.locate(self.coords.round(), quick=True)).countrycode)
         return [language for language in result][:4] + ['en']
      except:
         return ['en']

   @property
   @utils.cache(16)
   def category(self):
      if self.official or self.sources: return "earthquake"

      for language in self.languages:
         for label in ["earthquake", "alert"]:
            if any(keyword in keywords.get(label, language=language) for keyword in self.keywords):
               utils.log("Determined category %r from %r" % (label, self.keywords))
               return label

      utils.log("Defaulting to category 'earthquake'")
      return "earthquake"

   def supersedes(self, other, throttling=120):
      if self.early and not self.official: return False

      if not self.confidence >= other.confidence and not self.status > other.status: return False

      # This should happen elsewhere, but anyway
      if not self == other: return False

      confidence = max(clip(self.confidence, 0.01, 1.0), clip(other.confidence, 0.01, 1.0))

#      if self.status > Report.Status('incomplete'):
#         utils.log("MANG, %r has status %r. Official? %r  (other: %r)" % (self, self.status, bool(self.official), other))

      if self.status > Report.Status('incomplete') and bool(self.tsunami) > bool(other.tsunami): return 'tsunami'
      if bool(self.official) > bool(other.official): return 'official'
#      if self.alert > Report.Severity('green') and self.alert > other.alert and len(self.sources) > len(other.sources): return str(self.alert)
      if self.alert > Report.Severity('green') and self.alert > other.alert: return str(self.alert)

      if self.mag - other.mag > clip(0.25/confidence, 0.15, 3.0): return 'stronger'
      if self.intensity and other.intensity and self.intensity > other.intensity: return 'worse'

      if self.timestamp - other.timestamp < throttling: return False

      if other.early and self.witnesses and self.warners and len(self.witnesses) - len(self.warners) == 10: return 'felt'
      if other.early and self.confidence > 0.5: return 'detailed'
      if other.mag - self.mag > clip(0.4/confidence, 0.3, 3.0): return 'weaker'
      if self.coords.radius < other.coords.radius and self.coords - other.coords > clip(self.radius + other.radius, 20, 300): return 'epicenter'
#      if self.alert == Report.Severity('green') and self.alert < other.alert and len(self.sources) > len(other.sources): return str(self.alert)
      if self.alert == Report.Severity('green') and self.alert < other.alert and len(self.sources) > len(other.sources): return str(self.alert)
      if self.intensity and not other.intensity: return 'detailed'

   def elapsed(self, minutes=10):
      return bool(self.time < When.now().subtract(minutes=minutes))

   @property
   def timely(self):
      if not self.elapsed(3): return 'warning'
      if not self.elapsed(7) and self.category != 'earthquake': return 'emergency'
      if not self.elapsed(10) and self.confidence >= 0.2: return 'breaking'
      if not self.elapsed(15) and self.confidence >= 0.4: return 'preliminary'
      if not self.elapsed(20) and self.confidence >= 0.2: return 'fresh'
      if not self.elapsed(60) and self.official: return 'official'
      if not self.elapsed(120) and self.tsunami: return 'tsunami'
      if not self.elapsed(self.alert.duration): return 'alert'
      if self.victims and not self.elapsed(clip(self.victims*100, 60*24, 60*24*7)): return 'victims'

   @property
   def early(self):
      if self.timely not in ['warning', 'emergency']: return False
      if self.category != 'earthquake': return self.category

      deadline = self.time.add(seconds=20.0+self.arrival(radius=self.radius+min(200, self.coords.radius)))
      utils.log("Deadline for arrival of {notice}: {time}".format(notice=self, time=deadline))
      return bool(deadline > When.now())

   @property
   def priority(self):
      return self.confidence * self.mag
#      return (max(0.1, self.confidence) if self.early else 0.1 if self.significance else 0.05 if self.timely else 0.01) * self.mag

   @utils.cache(16)
   @profile
   def announcements(self, term, caps=True, languages=None):
      translations = (keywords.get(term, language) for language in (languages or self.languages))
      translations = (synonyms[0].upper() if caps else synonyms[0].capitalize() for synonyms in translations if len(synonyms) > 0)

      return list(OrderedDict.fromkeys(translations))[:4]

   @property
   @profile
   def estimate(self):
      if self.category != "earthquake": return None
      status = 'early' if self.status < Report.Status('incomplete') else 'fuzzy' if self.status < Report.Status('preliminary') else 'exact'
      adjusted = self.mag #if status == 'exact' else Report.Magnitude(self.mag + 1.0) if self.rate > 2.0 else Report.Magnitude(self.mag - 1.0) if self.rate < 0.1 else self.mag

      try:
         return format(adjusted, status)
      except:
         utils.error("AINT WORKING {adj} ({typ}) {sta}".format(adj=adjusted, typ=type(adjusted), sta=status))
         return self.mag

   def messages(self, domain, style='long', languages=None):
      if not self.timely: return

      relevance = domain.relevance(self)
      significance = domain.significance(self)

      if not relevance: return

      utils.log("Determining messages of {notice} for {domain} with is early? {early}".format(notice=self, domain=domain, early=self.early))

      languages = tuple(languages) if languages else None
      keyword = self.keyword.capitalize() if self.keyword else self.announcements(self.category, caps=False, languages=languages)[0]

      def wrap(warning):
         if warning:
            prefix = u"❗ " if self.early or self.tsunami else u""
            pattern = "{warning}. From {source}." if style in ['human'] else "{prefix}{warning}" if "http" in warning and style in ['short'] else "{prefix}{warning} ({source})"
#            return pattern.format(prefix=prefix, warning=warning, source=("Twitter: API access ending soon!" if unicode(self.provider) == "Twitter" else self.provider))
            return pattern.format(prefix=prefix, warning=warning, source=self.provider)

      def minimal(domain):
         if not domain.target or not self.early or not significance: return
         if self.time.add(seconds=self.arrival(location=domain.target)) < When.now(): return

         yield self.announcements("earthquake warning", languages=languages)[0] if self.category == "earthquake" else keyword.upper()

      def arrival(domain):
         if not domain.target or not self.early or not significance: return

         bold, italic = ("\x02%s\x02", "\x1d%s\x1d")

         strength = (1.0 - (self.coords - domain.target) / self.radius) * (self.mag / 6.0)
         strength = 'very strong' if strength > 0.95 else 'strong' if strength > 0.8 else 'moderate' if strength > 0.5 else 'weak'

         arrival = self.time.add(seconds=self.arrival(location=domain.target))

         try: address = where.Address(where.locate(domain.target, quick=True)).tostring('human') or self.region
         except: address = self.region

         strength = bold % strength
         countdown = bold % format(arrival, "human")
         address = italic % address

         epicenter = where.Address(where.locate(self.coords, quick=True)).tostring('human')

         if not domain.debug:
            yield u"{keyword}: {strength} tremors possible {time} around {place} (reported from near {epicenter}).".format(keyword=keyword, strength=strength, time=countdown, place=address, epicenter=epicenter)
         else:
            yield u"Earthquake {event.region} {event.coords}, {event.mag}, depth {event.depth} km, occurred at {event.time}, felt at {target} ({address}, distance {distance}) at {arrival}".format(event=self, target=domain.target, address=address, arrival=arrival, distance=self.coords - domain.target)

         if arrival < When.now().subtract(seconds=10) or strength == bold % "weak": return

         yield "Cover your head and stay away from things that may fall. Leave doorways open."

         if arrival < When.now().subtract(seconds=20): return

         yield u"If there is enough time, shut off the gas valve."

      def warning(domain):
         if domain.target or not self.early or not significance: return  # was ... or not relevance == 'significance'

         warnings = self.announcements("earthquake warning", languages=languages) if self.category == 'earthquake' else [self.category.capitalize()]
         warnings = self.red % u' / '.join(warnings)
         place = where.Address(where.locate(self.coords, quick=True)).tostring('human')
         region = self.region if self.category == 'earthquake' else u": ".join({self.region, where.Address(where.locate(self.coords.round(), quick=True)).country})

         yield u"{warnings} for {region} (＃{keyword} reported near ＃{place}?)".format(warnings=warnings, region=region, place=place, keyword=keyword)

      def tsunami(domain):
         if not self.children[0].tsunami and not self.best[0].tsunami: return

         warnings = self.announcements("possible tsunami", languages=languages)
         warnings = self.red % u' / '.join(warnings)
         localities = max(filter(None, [self.best[0].tsunami, self.children[0].tsunami, self.tsunami]), key=len)
         links = [report.links[0] for report in self.official if report.links] or tsunami_sites

         yield u"{warnings} for {place}! 🌊 Monitor {links}".format(warnings=warnings, place=localities, links=' '.join(links))

      def felt(domain):
         if self.early or self.official: return
         if not self.witnesses or not self.warners or (len(self.children) - len(self.warners)) % 32 == 0: return
         if self.timely not in ['warning', 'breaking', 'fresh']: return
         if not self.impacted: return

         max = 3 if style in ['human'] else 6 if style in ['short'] else 12

         if style in ['human']: pattern = u"{event.region} felt an earthquake at {places}"
         else:                  pattern = u"{event.icons[felt]} Recent \x02{event.region}\x02 earthquake might be felt near {places}"

         yield pattern.format(event=self, places=", ".join(self.impacted[:max]))

      def details(domain):
         if self.category == 'earthquake':
            if self.early and not self.official: return
            if self.confidence < 0.2 and not self.official: return # Don't get caught in calculating hit towns and populations, it slows down everything
            if domain.target and not self.official: return # Don't bother users with private messages that could be repeated noise
         else:
            if self.early or self.confidence < 0.1: return

         try:
            highlight = relevance
            marker = self.icons[relevance]
            marker = self.icons['tentative'] if not self.official else marker
            if keyword: marker = "{icon} {keyword}".format(icon=marker, keyword=keyword)
         except KeyError:
            highlight = significance or self.significance
            shouts = self.announcements(self.category, caps=False, languages=languages) if self.category == 'earthquake' else [keyword]
            shouts = ([keyword] + shouts) if keyword and keyword not in shouts else shouts
            shouts = [u"＃" + announcement + ('!' if self.official else '?') for announcement in shouts] # full-width hash will be replaced later with either regular hash for hashtag, or nothing
            shouts = shouts[:1] if style in ['human'] else shouts[:2] if style in ['short'] else shouts[-1:] if style in ['machine'] else shouts
            marker = "{icon} {shouts}".format(icon=self.icons.get(self.significance, self.period), shouts=u' '.join(shouts))

         yield "{marker} {details}".format(marker=marker, details=self.details(style=style if style in ['fixed'] or relevance else 'short', highlight=highlight))

      def feedback(domain):
         if not domain.target: return # Only send this to individuals
         if self.early: return # Don't bother them if it's an early warning
         if self.icons.get(relevance): return # Don't bother them if it's an update, either
         if not self.official: return

         distance = self.coords - domain.target

         if distance < self.radius*0.5: return # People close to the epicenter have felt it, period

         try: address = where.Address(where.locate(domain.target)).tostring('human') or "your location"
         except: address = "your location"

         if distance < self.radius:
            yield "{place} is about {distance:.0f} km from the epicenter. Did you feel it?".format(place=address, distance=distance)
         else:
            yield "At {distance:.0f} km from the epicenter you likely couldn't feel this in {place}.".format(place=address, distance=distance)


      messages = (minimal, warning, tsunami, felt, details, arrival) #, feedback)
      messages = (message(domain) for message in messages)

      try:
         for message in messages:
            for line in message: yield wrap(line)
      except:
         utils.error("Failed sending message")

   @property
   def globe(self):
      if self.depth > 200: return u'🌐'
      if 'Japan' in self.region: return u'🗾'

      return u'🌍' if -30 < self.coords.lon < 55 else u'🌎' if self.coords.lon < 0 else u'🌏'


   @property
   @utils.cache(16)
   @profile
   def title(self):
      banner = ' - '.join(self.announcements("earthquake", caps=False)) if self.category == 'earthquake' else self.category.capitalize()
      #exactness = 'early' if self.confidence < Report.Status('incomplete') else 'fuzzy' if self.confidence < Report.Status('preliminary').confidence else 'exact'

      try:
         source = self.best[0].sources[0] if len(self.best[0].sources[0]) == 1 else self.provider
      except:
         source = self.provider

      style = "{icon} {event.region}: {banner} ({event.estimate}, at {event.time:short}, from {source})"
      return style.format(event=self, icon=self.globe, banner=banner, source=source)

   @utils.cache(16)
   @profile
   def details(self, style='long', highlight=False):
      italic = "\x1d%s\x1d"
      count = 1 if style == 'human' else 4 if style == 'short' else 6 if style == 'long' else 5

      output = Statement(style, highlight, data=self)

      fast = True if style in ['machine'] else False

      try:    population = round(max(sum(self.populations), len(self.witnesses)), -2) if not fast else None
      except: population = None

      if self.alert:                 output.append("{data.alert:uc} alert:", alert=True, green=True, yellow=True, orange=True, red=True)
      if self.estimate:              output.append("{data.estimate},", long="{data.estimate} tremor,", human="magnitude {data.estimate},", magnitude=True, weaker=True, stronger=True)
      if 0 < len(self.agencies) < 4: output.append("registered by {agencies},", short=None, human=None, agencies=','.join(sorted(self.agencies)))
      elif self.agencies:            output.append("registered by {count} agencies,", short=None, human=None, count=len(self.agencies))
      if len(self.witnesses) > 1:    output.append("with {count} reports,", short=None, human=None, fixed=None, count=len(self.witnesses))
      if self.warners:               output.append("{count} early,", short=None, human=None, fixed=None, count=len(self.warners))
      if fast:                       pass
#      elif not self.rate:            output.append("unknown frequency,", human=None, short=None, fixed=None, machine=None)
#      elif self.rate < 0.5:          output.append("expected every {frequency:.0f} years,", short="one in {frequency:.0f} years,", human=None, machine=None, frequency=1.0/self.rate)
#      elif 0.5 <= self.rate < 1.5:   output.append("expected yearly,", short="yearly,", human=None, machine=None, frequency=True)
#      elif 1.5 <= self.rate < 2.5:   output.append("expected twice a year,", short="frequent,", human=None, machine=None, frequency=True)
#      elif self.rate >= 2.5:         output.append("expected {data.rate:.0f} times a year,", short="very frequent,", human=None, frequency=True)
      if not self.official:          output.append("possibly", confidence=True)
      if self.time:                  output.append("{time:{style}}", long="occurred {time:{style}},", human="{time:human},", time=self.time, style=style)
      if self.solar == 'night':      output.append("({moon} moon),", long="during a {moon} moon night,", human="during the night,", short=None, moon=self.lunar)
      else:                          output.append("({sun})", long="during {sun},", human="during {sun},", short=None, sun=self.solar)
      if self.water is not None:     output.append("on water ({self.water}),".format(self.water) if self.water else "on land,")
      if self.coords:                output.append("{place} {epicenter}", human="around {place},", place=italic % self.place(style), epicenter=self.coords)

      if self.category == 'earthquake':
         if not fast and self.radius:   output.append("likely felt {radius:.0f} km away", short="felt to {radius:.0f} km", human=None, felt=True, radius=round(self.radius, -1))
         if not fast and self.impacted: output.append("(in {towns}…)", human="felt in {towns},", machine=None, towns=", ".join(self.impacted[:count]))
         if not fast and population:    output.append("by {population} people", short="by {population}", human="by {population} people", machine=None, population=humanize.intword(population))
         if self.victims:               output.append("with {victims} victims", short=", {victims} victims,", machine=None, victims=self.victims)
         if not fast and self.nuclear:  output.append("with {data.nuclear} nearby reactors", short="and {data.nuclear} reactors")
         if self.tsunami:               output.append("with possible tsunami", short="(TSUNAMI?)", tsunami=True)
         if self.intensity:             output.append("with maximum intensity {data.intensity}", short=u"– intensity: {data.intensity}", worse=True)

      if self.links:                 output.append("→ {links}", human=None, machine=None, links=" ".join(set(self.links[:int(count/1.6)])))
      if not fast and self.webcams:  output.append("— Webcams: {webcams}", short=None, machine=None, human=None, webcams=" ".join(self.webcams[:count]))

      return unicode(output)

   @property
   @utils.cache(16)
   def significance(self):
      if self.victims: return 'victims'
      if self.tsunami: return 'tsunami'
      if self.mag > 7.0: return 'magnitude'
      if self.mag > 6.5 and self.depth < 300: return 'magnitude'
      if self.mag > 6.0 and self.alert > Report.Severity('green'): return 'magnitude'
      if self.mag > 5.0 and self.alert > Report.Severity('yellow'): return str(self.alert)
      if self.mag > 6.0 and self.depth < 200 and exceeds(self.populations, 100): return 'magnitude'
      if self.mag > 5.0 and self.depth < 150 and exceeds(self.populations, 100000): return 'population'
      if self.mag > 4.5 and self.rate and self.rate < 0.01: return 'frequency'
#      if self.category != 'earthquake': return 'emergency'    is this causing it NOT to show?

   @property
   @utils.cache(16)
   @profile
   def impacted(self):
      def distance(coords, geometry):
         return min(node - coords for node in where.Coords.fromgeometry(geometry))

      def damage(name, geometry, properties):
         return float(properties.get('population', 100)) * (2.0**(-properties['distance']/20.0))
         #except: return 100 # token value - utils.log("{props[name]!r} has invalid population {props[population]!r}".format(props=features.properties))

      def felt(name, geometry, properties):
         reports = [witness for witness in self.witnesses if distance(witness.coords, geometry) < 7.0]
         if reports: utils.log("Witnesses for %r: %r" % (name, reports))
         return sum(report.confidence for report in reports) / float(properties.get('population', 100))

      for criterion in felt, damage:
         try:
            places=[(criterion(name, geometry, properties), name) for name, geometry, properties in self.localities(self.radius)]
            places=[name for score, name in sorted(places, reverse=True) if score > 0]
            if places: return places
         except:
            utils.error("Could not determine settlements")

      return []

   @property
   def populations(self):
       for name, geometry, properties in self.localities(self.radius):
          if properties.get('population'):
             yield properties['population']

   @profile
   def localities(self, radius):
       if self.early or self.status < Report.Status('incomplete') or self.score < 0.05 or slowdown.factor > 3: return

       utils.log("Processing localities for %r" % self)

       previous = []

       threshold = min(300 if self.water else 120, int(radius))  # should be higher than 120, speed allowing

       for radius in range(5, threshold, max(int(round(threshold/5.0, -1)), 10)):
#          types = '(city|town|village|hamlet)' if radius < 50 else '(city|town)' if radius < 100 else '(city)'
          types = '(city|town)' if radius < 50 else '(city|town)' if radius < 70 else '(city)'
          places = []

          try: places = where.osm(self.coords.round(1), radius, timeout=30, **{'population': int, 'place': types})
          except: utils.error("Couldn't get localities")

          places = [(place.properties['name'], place.geometry, place.properties) for place in places if place.properties.get('name')]

          for name, geometry, properties in places:
             if name not in previous:
                yield name, geometry, properties
             previous.append(name)

   @property
   @utils.cache(16)
   def webcams(self):
      # Try leaving the webcams alone to see if it gets faster and/or stops having posts removed from Reddit
      return []

      if self.score < 0 or self.mag < 4.8: return []
      if self.solar in ['night']: return []

#      try: return [utils.shorten(link) for link, title in where.webcams(self.coords, self.radius*0.8, live=False)[:3]]
      try: return [link for link, title in where.webcams(self.coords, self.radius*0.8, live=False)[:3]]
      except: utils.error("Could not get nearby webcams")

   @property
   @utils.cache(16)
   def nuclear(self):
      if self.status < Report.Status('incomplete') or self.score < 0 or self.mag < 4.5: return 0

      try: return len(where.osm(self.coords.round(1), int(self.radius*0.6), timeout=20, **{'generator:source': 'nuclear'}))
      except: utils.error("Could not get nearby reactors")

   @property
   @utils.cache(16)
   def rate(self):
      url = "http://api.openhazards.com/GetEarthquakeProbability"

      return None # API long dead

      if self.status < Report.Status('incomplete') or self.score < 0 or self.mag < 2.5: return

      try:
         radius = int(self.radius if not self.water else self.radius*3.0)
         mag = round(self.mag, 1)
         response = utils.web.get(
            url,
            timeout=5,
            params={'q': "{coords.lon:.3f},{coords.lat:.3f}".format(coords=self.coords), 'm': mag, 'r': radius}
         )
         rate = float(next(ElementTree.fromstring(response.text).iter("rate")).text)
         return rate
      except:
         utils.error("Could not get rate of event from for %r" % self)

   @property
   def agencies(self):
      word = re.compile(r'\w*')

      sources = {source for child in self.children for source in child.sources if source}
      sources = {word.search(source).group() for source in sources}
      sources = {source if len(source) > 3 else source.upper() for source in sources if source}

      return sources

   @property
   def solar(self):
      elevation = Astral().solar_elevation(self.time.datetime(), latitude=self.coords.lat, longitude=self.coords.lon)

      return 'daytime' if elevation > 6 else 'twilight' if -6 < elevation < 6 else 'night'

   @property
   def lunar(self):
      phase = Astral().moon_phase(self.time.datetime(), float)

      return 'new' if phase > 27 or phase < 1 else 'full' if 13 < phase < 15 else 'crescent' if phase < 7 or phase > 21 else 'gibbous'

   @property
   def period(self):
      sun, moon = self.solar, self.lunar

      if sun == 'daytime':  return self.globe
      if sun == 'twilight': return u'🌅' if self.water else u'🌆' if self.significance in ['population'] else u'🌄'
      if sun == 'night':    return u'🌕' if moon == 'full' else u'🌑' if moon == 'new' else u'🌖' if moon == 'gibbous' else u'🌒'


class Threshold(object):
   def __init__(self, initial=0.05, sigmas=0.5):
      self.sigmas = sigmas
      self.averages = {hour: initial for hour in range(0, 24)}
      self.variances = {hour: 0.0 for hour in range(0, 24)}

   def update(self, value, hit=True):
      weight = 0.2
      value = self.averages[self.hour] + value if not hit else value
      self.averages[self.hour] = self.averages[self.hour]*(1-weight) + value*(weight)
      self.variances[self.hour] = self.variances[self.hour]*(1-weight) + ((value - self.averages[self.hour])**2)*(weight)

   @property
   def hour(self): return When.now().hour

   @property
   def average(self): return statistics.mean(self.averages.values())

   @property
   def variance(self): return statistics.mean(self.variances.values())

   @property
   def minimum(self):
      average, variance = self.average, self.variance

      for offset in [0, -1, +1, -2, +2, -3, +3]:
         weight = 1.0/(abs(offset)+2)
         try:
            average = average*(1-weight) + self.averages[self.hour + offset]*weight
            variance = variance*(1-weight) + self.variances[self.hour + offset]*weight
         except: continue

      return average + (variance**0.5)*self.sigmas

   def __format__(self, style):
      return "{threshold.average} average, {threshold.minimum} minimum".format(threshold=self)


class Domain(object):
   templates = {}
   database = {}

   def __init__(self, name=None, mag=None, box=None, target=None, radius=None, region=None, score=None, warning=False, alert=None, people=None, rate=None, age=7200, empty=False, threshold=None, updates=True, reports=None, categories=None, debug=False):
      self.name = name
      template = type(self).templates.setdefault(name, self) if name else None
      template = template if template is not self else None

      self.mag = Report.Magnitude(mag) if mag else template.mag if template else Report.Magnitude(3.0)
      self.box = (where.Coords(box[0]), where.Coords(box[1])) if box else template.box if template else None
      self.target = where.Coords(target, radius=radius if radius else template.target.radius if template and template.target else None) if target else template.target if template else None
      self.region = region if region else template.region if template else None
      self.score = score if score else template.score if template else 0.09
      self.warning = warning if warning else template.warning if template else False
      self.alert = Report.Severity(alert) if alert else template.alert if template else False
      self.people = people if people else template.people if template else False
      self.rate = rate if rate else template.rate if template else None
      self.empty = empty if empty else template.empty if template else False
      self.threshold = threshold if threshold else template.threshold if template else None
      self.updates = updates if updates else template.updates if template else False
      self.reports = reports if reports else template.reports if template else None
      self.categories = categories if categories else template.categories if template else ["earthquake"]
      self.debug = debug

      if self.threshold: self.threshold = self.database.setdefault(self, self.threshold)

      self.title = None

      self.history = deque(maxlen=64)
      self.last = None
      self.timestamp = When.now()
      self.lock = RLock()

   def __lt__(self, other):
      if self.target and not other.target: return True
      if self.warning and not other.warning: return True
      if self.alert and not other.alert: return True
      if self.people and not other.people: return False
      if self.people < other.people: return True
      if self.rate and not other.rate: return False
      if self.mag > other.mag: return True
      return False

   def significance(self, notice):
      # This is the whole thing that decides whether a Notice is relevant to a Domain.
      # A Domain is a pretty terrible thing that long ago already I meant to replace with a "composition" of classes,
      # where each class would represent, say, a magnitude, or a box. But instead there is that huge list of
      # parameters in __init__ and this huge list of ifs still. I was working on that with quup but then he disappeared...
      # Anyway, yeah :P the box stuff is in here with many other deciding things

      if self.empty:
         return False

      if self.categories:
         if notice.category not in self.categories: return False
         else: reason = 'emergency'

      if self.threshold and self.early and len(notice.warners) > 2:
         regional = Domain(region=notice.region, threshold=Threshold(initial=self.threshold.minimum, sigmas=self.threshold.sigmas))
         if notice.confidence < (self.threshold.minimum*0.8 + regional.threshold.minimum*0.2): return False
         else: reason = 'warning'

      if self.score:
         if notice.score < self.score or notice.confidence < self.score: return False
         else: reason = 'confidence'

      if self.mag and notice.category == 'earthquake':
         if notice.mag < self.mag: return False
         else: reason = 'magnitude'

      if self.alert:
         if self.alert > notice.alert: return False
         else: reason = 'alert'

      if self.reports:
         if self.reports > len(notice.witnesses): return False
         else: reason = 'felt'

      # I often use this instead of a box, it checks whether a substring like "Italy" is in the earthquake's region
      # such as "Central Italy", but this time I've used an actual box
      if self.region:
         if not re.search(self.region, notice.tsunami or notice.region, flags=re.IGNORECASE): return False
         else: reason = 'region'

      # So here it is, and as far as I know it works even though you must be careful to define the right
      # set of coordinates (on a map northern emisphere: bottom-left, top-right)
      # But anyway I originally didn't even have a box at all for the war stuff here, I would just post
      # any event (or at least I was *trying* to post them), so I don't think this is the code that can be
      # wrong. Besides, in #brainstorm where I get a lot of debug stuff, I still report "all" events
      # rather than a box.
      if self.box:
         a, b = self.box[0], self.box[1]
         if not a.lat < notice.coords.lat < b.lat or not a.lon < notice.coords.lon < b.lon: return False
         else: reason = 'epicenter'

      if self.target:
         if abs(notice.coords.lat - self.target.lat) > 1000.0/110.0: return False
         if abs(notice.coords.lon - self.target.lon) > 1000.0/60.0: return False
         if notice.coords - self.target > (self.target.radius or notice.radius): return False
         else: reason = 'felt'

      if self.warning:
         utils.log("Warning-specific check: is {notice} early for {domain}? {answer}".format(notice=notice, domain=self, answer=notice.early))
         if not notice.early: return False
         else: reason = 'warning'

#      if self.reports:
#         if not notice.witnesses or len(notice.witnesses) % self.reports: return False
#         else: reason = 'felt'

      if self.rate:
         if notice.rate and notice.rate > self.rate: return False
         elif notice.significance not in ('magnitude', 'population'): return False
         else: reason = 'frequency'

      if self.people:
         if not exceeds(notice.populations, self.people): return False
         else: reason = 'population'

#      if self.age:
#         if quake.time < When.now().subtract(seconds=self.age): return False

      return reason

   def remember(self, notice):
      with self.lock:
         while True:
            try: self.history.remove(notice)
            except: break

         self.history.append(notice)

         if len(self.history) > 30: utils.log("History exceeds 30 for %r" % self)

   def relevance(self, notice):
      with self.lock:
         for other in self.history:
            if notice == other:
               notice.tag = other.tag
               self.confirm(other, notice)
               self.last = notice
               return notice.supersedes(other) if self.updates or (not other.official and notice.official) else None

      self.last = notice
      if self.significance(notice): return 'significance'

   def confirm(self, notice, confirmation):
      if confirmation.status >= Report.Status('incomplete') > notice.status and len(notice.warners) > 2:
         for domain in (self, Domain(region=notice.region)):
            if not domain.threshold: continue

            domain.threshold.update(sum(witness.confidence for witness in notice.warners))
            domain.database[domain] = domain.threshold
            utils.log("Threshold for {domain!r} changed to {domain.threshold}".format(domain=domain))

   def __repr__(self):
      values = []

      for attribute, name in [
         (self.name, 'name'),
         (self.region, 'region'),
         (self.target, 'target'),
         (self.box, 'box'),
         (self.mag, 'mag'),
         (self.score, 'score'),
         (self.warning, 'warning'),
         (self.alert, 'alert'),
         (self.people, 'people'),
         (self.rate, 'rate'),
         (self.updates, 'updates'),
         (self.reports, 'reports'),
         (self.categories, 'categories'),
      ]:
         if attribute: values.append("{name}={value}".format(name=name, value=attribute))

      return "{cls}({description})".format(cls=type(self).__name__, description=", ".join(values))


   def __unicode__(self): return unicode(self.name)


class Rule(object):
    def __init__(self, match): self.match = match

    def __add__(self, other): return Domain([self, other])

class Target(Rule):
    def __contains__(self, event): return event.coords - self.match < event.radius

class MinMag(Rule):
    def __contains__(self, event): return quake.mag > self.mag

class Unknown(Rule):
    def __contains__(self, event): return event not in self.match

class Criteria(Rule):
    def __contains__(self, event): return all(event in rule for rule in self.match)


class Monitor(Worker):
    # This should be an instance variable really, but we're making it global because
    # it's used elsewhere in a hacky way to determine if the bot is "busy", and
    # given this class is only likely to be instantiated once anyway...
    locks = {region.title(): Lock() for region in where.regions.names}

    def __init__(self, queue):
       self.stats = shelve.open("quakes.log", writeback=False)
       self.recipients, self.uniques = [], set()
       self.targets = []
       self.start(input=queue, threads=2)
       self.started = When.now()
       self.stopwatch = Stopwatch("Consuming events")

    notifystopwatch = Stopwatch("Notifying people")

    def notify(self, recipient, languages, *domains):
       with self.notifystopwatch:
          if recipient not in self.uniques: self.uniques.add(recipient)
          else: return

          for domain in domains: self.recipients.append((recipient, domain, languages))

          self.recipients.sort()

       utils.log("Recipient {recipient} will receive alerts for domains {domains} in {langs}".format(recipient=recipient, domains=domains, langs=languages))

    def process(self, notice, origin):
       delay = When.now().epoch - notice.timestamp
       utils.log("Consuming event pri {notice.priority} gotten {time:.1f} sec ago from {notice.provider}: {notice}".format(time=delay, notice=notice))

       if delay > 60:
          Matrix(DEBUG_ROOM).send("Error", "WARNING: event from %r delayed by %r seconds" % (type(notice.provider), delay))
          utils.log("{time} seconds are too many!".format(time=delay))
          slowdown.factor *= 1.0 + delay/600.0
          if notice.confidence < 0.3 and delay > 120: return
       elif delay < 10:
          slowdown.factor = max(1.0, slowdown.factor*0.8)

       if slowdown.factor > 64:
          Matrix(DEBUG_ROOM).send("Error", "WARNING: restarting bot due to excess delay")
          IRC(IRC_OWNER).send("Error", "WARNING: restarting bot due to excess delay")
#          Twitter().send("Error", "🚧 The bot is overloaded. Reports may not be available for some time.")
          utils.log("Well, restarting bot then, factor is {factor}".format(factor=slowdown.factor))
          time.sleep(30)
          os._exit(os.EX_SOFTWARE)

       if notice.score < 0 or not notice.timely: return
       if notice.status <= Report.Status('guessed') and self.locks[notice.region].locked():
          utils.log("(Consuming) IGNORING notice %r" % notice)
          return

       highlights = {IRC, Matrix}
       delivered = {}
       deliveries = []
       text = None

       with self.locks[notice.region], self.stopwatch:
          utils.log("(Locking) Consuming event pri {notice.priority} gotten {time:.1f} sec ago from {notice.provider}: {notice}".format(time=delay, notice=notice))
          targets = [(recipient, domain, notice.messages(domain, style=recipient.style, languages=languages)) for recipient, domain, languages in self.recipients]
          utils.log("(Targets) Consuming event with %r targets" % len(targets))
          utils.log("(Computed) Consuming event pri {notice.priority} gotten {time:.1f} sec ago from {notice.provider}: {notice}".format(time=delay, notice=notice))

          while targets:
             utils.log("(Looping) Consuming event pri {notice.priority} gotten {time:.1f} sec ago from {notice.provider}: {notice}".format(time=delay, notice=notice))

             for recipient, domain, messages in list(targets):
                try:
                   if delivered.get(recipient, domain) is not domain: raise RuntimeError("Already sent for another domain")
                   text = next(messages)
                except Exception as e:
                   if recipient in delivered:
                      utils.log("Considering delivered for {target}'s {domain1} through {domain2}".format(target=recipient, domain1=domain, domain2=delivered.get(recipient)))
                      domain.remember(notice)

                   if type(e) not in [StopIteration, RuntimeError]: utils.error("(Discarding) Consuming event got exception")

                   targets.remove((recipient, domain, messages))
                   continue

                if not domain.target and type(recipient) in highlights and notice.early:
                   nicknames = [person.nickname for person in delivered if type(person) is type(recipient) and delivered[person].target]
                elif not notice.early and domain.relevance(notice) in ['significance', 'official', 'tsunami']:
#                   nicknames = [witness.user.nickname for witness in notice.witnesses if witness.score > 0 and type(witness.user) is type(recipient)]   don't actually highlight a bunch of Twitter users and "disclose" their location in the process, it's also against TOS
                   nicknames = []
                else:
                   nicknames = []

                utils.log("(Consuming) Sending for domain %r, %r, pri %r" % (domain, recipient, notice.priority))

                try:
                   recipient.send(notice.title, text, coords=notice.coords, tag=notice.tag, pings=nicknames, urgent=(notice.early and not domain.debug))
                   if domain.target: deliveries.append(recipient)
                except: utils.error("Cannot SEND MESSAGE!")

                utils.log("MESSAGE {notice} concerns {target} in {domain} due to {relevance} ({significance})".format(
                   notice=notice,
                   target=recipient,
                   domain=domain,
                   relevance=domain.relevance(notice),
                   significance=domain.significance(notice))
                )

                delivered.setdefault(recipient, domain)

                break

             if delivered:
                self.log(notice)
                yield

             utils.log("(Done) Consuming for %r, %r" % (domain, recipient))

          if deliveries:
             IRC(IRC_OWNER).send("Earthquake report sent", "Sent {title} to ".format(title=notice.title) + ", ".join(repr(delivery) for delivery in set(deliveries)))

    @profile
    def log(self, notice):
       provider = format(notice.provider, "url")
       self.stats[str(provider)] = self.stats.get(str(provider), 0) + 1

       for source in notice.sources:
          self.stats[str(source)] = self.stats.get(str(source), 0) + 1

       self.stats.sync()
       database.sync()


def slowdown(alerts):
    if alerts: utils.log("Throttling feed polling due to %s" % ", ".join(alerts))
    slowdown.factor = len(alerts)+1.0

slowdown.factor = 1.0


def setup(bot):
    global manager
    global monitor
    global database
    global europe

    #europe = Domain(box=((35, -10), (80, 35)), score=0.001, categories=['alert'])

    Recipient.bot(bot)
    where.setup(bot)

    try: Domain.database = storage.Database(storage.path(bot, "thresholds"), writeback=False)
    except: utils.error("Couldn't open thresholds database")

    database = shelve.open(utils.database(bot, "alerts"), writeback=True)
    if 'earthquake' not in database: database['earthquake'] = deque(maxlen=64)

    manager = FeedManager(Dispatcher(FeedParser), history=database['earthquake'])

    try: manager.add(Twitter())
    except: utils.error("Could not log in to Twitter")

    monitor = Monitor(manager)

    IRC(IRC_OWNER).send("Startup", "Started monitor")

    def initialize():
       utils.log("Initializing quake feeds...")

       if hasattr(bot.config, 'quake_feeds'):
          for feed in bot.config.quake_feeds: manager.add(feed.format(yesterday=When.now().subtract(days=1).iso8601()))

       time.sleep(60)

       utils.log("Initializing built-in recipients...")

       for recipient, domains, languages in default_recipients():
          try: monitor.notify(recipient, languages, *domains)
          except: utils.error("CANNOT NOTIFY %r" % recipient)

       utils.log("Initializing Twitter recipients...")

       counter = len(monitor.recipients)

       locations = shelve.open(utils.database(bot, "locations"), writeback=False)

       for follower in Twitter().followers:

          location, timestamp = locations[repr(follower)] if repr(follower) in locations else (None, None)

          if not timestamp or timestamp > time.time() + 3600*24*7*(random.random()+0.5):
             time.sleep(2)
             utils.log("Figuring out uncached location of Twitter recipient {recipient}".format(recipient=follower))
             location, timestamp = (follower.coords, time.time())
             locations[repr(follower)] = (location, timestamp)
             locations.sync()

          if not debug and location:
             utils.log("Location of Twitter recipient {recipient} resolves to {place}".format(recipient=follower, place=location.placename))
             monitor.notify(follower, ['en'], Domain(target=location))
             time.sleep(0.1)

       locations.close()

    Thread(target=initialize).start()

    def print_scores(tick, origin):
       utils.log("Worst tweeters: %r" % list(sorted(TwitterParser.scores.items(), key=lambda (id, score): score, reverse=False))[:32])
       utils.log("Best tweeters: %r" % list(sorted(TwitterParser.scores.items(), key=lambda (id, score): score, reverse=True))[:32])
       utils.log("Running threads (%r): %r" % (len(threading.enumerate()), threading.enumerate()))
       yield

    dumper = Worker(processor=print_scores)
    dumper.start(input=dumper.ticker(seconds=300))

    Event.stats = shelve.open(utils.database(bot, "heuristics"))
    learner = Worker(processor=Event.model)
    learner.start(input=learner.ticker(seconds=300))

#    Timer(60, lambda: bot.chill(callback=slowdown)).start()

    utils.log("Finished setting up")


def simulate(bot, input):
   global manager

   parsed = bot.chat.parse(input, filter=r'^(?P<mag>[\d.]+) +(?P<location>.*)$')
   if parsed.error: return bot.chat.message(input, parsed.error)

   try:
      coords = where.Coords(parsed.match.group('location'))
   except:
      location = where.locate(parsed.match.group('location'))
      if not location: return bot.chat.message(input, "I don't know where that is!")
      coords = where.Coords(location.point)

   coords.point.altitude = -10
   mag = float(parsed.match.group('mag'))

   notice = Notice(Report(coords=coords, mag=mag, time=When.now().subtract(seconds=5), score=1.0))
   bot.chat.message(input, "Simulated event: ", notice.messages(Domain(mag=1.0)))

   if not input.admin: return

   bot.chat.message(input, "Simulating earthquake at %s..." % coords)

   beginning = When.now().subtract(seconds=5)

   for i in range(40):
      quake = Report(coords=coords, mag=mag+random.normalvariate(0, 0.6), time=When.now().subtract(seconds=5), score=0.03, keyword=u"esplosione")
      quake.status = Report.Status('guessed')
      manager.put((quake, FakeReceiver()))
      time.sleep(4)

   for update in ('incomplete', 'detection', 'confirmed', 'revised'):
      severities = ['green', 'yellow', 'orange', 'red']
      time.sleep(10)
      alert = Report.Severity(random.choice(severities))
      quake = Report(coords=coords, mag=mag+random.normalvariate(0, 2.0), alert=alert, time=beginning, score=0.9, keyword=u"esplosione")
      quake.status = Report.Status(update)
      manager.put((quake, FakeReceiver()))


   bot.chat.message(input, "End of simulation.")

simulate.commands = ['simulate']
simulate.hidden = True
simulate.thread = True


def quakes(bot, input):
   parsed = bot.chat.parse(input)
   if parsed.error: return bot.chat.message(input, parsed.error)

   location = where.locate(parsed.text)
   if not location: return bot.chat.message(input, "I don't know where that is!")

   domain = Domain(target=location.point, radius=1000)
   descriptions = [notice.details(style='machine') for notice in reversed(list(manager.history)) if domain.relevance(notice)]

   bot.chat.message(input, "Recent quakes near %s: " % where.Address(location).tostring('long'), descriptions)

quakes.commands = ['quakes']


def lastquake(bot, input):
   earthquakes = set()

   for recipient, domain, languages in monitor.recipients:
      utils.log("Since %r = %r, outputting from %r: %r" % (str(recipient), input.sender, domain, domain.last))
      if str(recipient).lower() == input.sender.lower() and domain.last: earthquakes.add(domain.last)

   earthquakes = sorted(earthquakes, key=lambda event: event.time, reverse=True)

   if earthquakes:
      bot.chat.message(input, "Last reports: ", [notice.details(style='short') for notice in earthquakes])
   else:
      bot.chat.message(input, "No relevant earthquakes reported recently (or the bot was restarted)")

lastquake.commands = ['lastquake', 'quake', 'earthquake']


def tweets(bot, input):
   def dump(tick, origin):
      results = []

      for word, count, coords in TwitterParser.tweetbag.top()[:10]:
         if coords:
            try: place = where.Address(where.locate(coords)).tostring('short')
            except: place = coords
            if coords.radius: results.append("%s (%d, %d km around %s)" % (word, count, coords.radius, place))
            else: results.append("%s (%d, near %s)" % (word, count, place))
         else:
            results.append("%s (%d)" % (word, count))

      bot.chat.message(input, "Twitter stats: ", results)

      yield

   parsed = bot.chat.parse(input)
   location = where.locate(parsed.text) if parsed.text else None

   if location:
      southwest = where.Coords(location.point)+where.Coords((-2, -2))
      northeast = where.Coords(location.point)+where.Coords((2, 2))

      bot.reply("Monitoring area (%d, %d)-(%d, %d)" % (southwest.lat, southwest.lon, northeast.lat, northeast.lon))
      manager.focus('twitter', locations=[southwest.lon, southwest.lat, northeast.lon, northeast.lat])

   dumper = Worker(processor=dump)
   dumper.start(input=dumper.ticker(seconds=240))

tweets.commands = ['tweets', 'tweets from']
tweets.hidden = True


def tweeters(bot, input):
   bot.chat.message(input, "Worst tweeters: ", sorted(TwitterParser.scores.items(), key=lambda (id, score): score))

tweeters.commands = ['tweeters']
tweeters.hidden = True


def common_words(bot, input):
   bot.chat.message(input, "Most common terms: ", ["%s: %s" % pair for pair in TwitterParser.terms.most_common(10)])

common_words.commands = ['commonwords']
common_words.hidden = True


def thresholds(bot, input):
   domains = list(Domain.database)
   print domains

   bot.chat.message(input, "Thresholds: ", ["{domain}={threshold}".format(domain=domain, threshold=Domain.database[domain]) for domain in domains])

thresholds.commands = ['thresholds']
thresholds.hidden = True


def default_recipients():
       # Examples
       Domain(name="Europe", box=((35, -10), (80, 35)))
       Domain(name="America", box=((26.5, -168.4), (71.3, -51)))
       Domain(name="Japan", region="Japan|Honshu|Ryukyu", score=0.08)
       Domain(name="Italy", region="Italy")
       Domain(name="SouthAmerica", box=((-57.3, -117.6), (27.7, -29.3)))
       Domain(name="Norden", box=((53.7,4.0), (71.2,31.2)))
       Domain(name="Delhi", target=(28.6139, 77.21596))
       Domain(name="Seoul", target=(37.56668, 126.97829))
       Domain(name="Tokyo", target=(35.683, 139.767))
       Domain(name="Athens", target=(37.98415, 23.72798))
       Domain(name="Istanbul", target=(41.05, 28.97))
       Domain(name="Ankara", target=(39.867, 32.833))
       Domain(name="London", target=(51.507, -0.128))
       Domain(name="Kuala Lumpur", target=(3.155, 101.714))
       Domain(name="UkraineWarzone", box=((45.43, 22.054), (52.6, 40.56)))

       # Examples
       if debug: return [
          (Matrix('#earthquakes:matrix.org'), [Domain(mag=2.5)], None),
          (Matrix('@user:server.org'), [Domain(name="Ankara")], ['tr']),
          (Mastodon(), [Domain(region="Europe")], None),
          (Twitter(), [Domain(mag=4.5)], None),
          (IRC('user1'), [Domain(name="Delhi")], ['hi', 'en']),
          (IRC('user2'), [Domain(target=(29.123, 28.123)), Domain(region="Turkey", mag=5.5, score=0.4)], None),
          (IRC('#monitoring-room'), [Domain(categories=['alert'], score=0.03), Domain(mag=3.5), Domain(rate=1.0), Domain(mag=6.0)], None),
          (Reddit('r/EEW'), [Domain(mag=4.6, warning=True), Domain(mag=5.5)], None),
          (Reddit('live/110m171zuj2cw'), [Domain(mag=2.5)], None),
          (File('earthquakes.log'), [Domain(mag=2.4)]),
       ]
      
