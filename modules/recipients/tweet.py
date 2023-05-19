#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
tweet.py - Send tweets and DMs on Twitter (may no longer fully work with the free API)

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

from modules.recipients import Recipient

import twitter
import tweepy
import re
import unicodedata
import time
import us.states
from cachetools import TTLCache

from modules import utils
from modules import where
from modules.timing import profile


class Twitter(Recipient):
    protocol = "twitter"
    style = 'short'
    priority = -10

    paragraph = "\n\n"
    hashtag = "#"

    maxlength = 270

    locations = TTLCache(maxsize=128, ttl=150)

    def initialize(self, service, consumer_key=None, consumer_secret=None, token_key=None, token_secret=None):
       api = twitter.Api(consumer_key, consumer_secret, token_key, token_secret, timeout=40, tweet_mode="extended")

       handler = tweepy.OAuthHandler(consumer_key, consumer_secret)
       handler.set_access_token(token_key, token_secret)
       self.tweepy = tweepy.API(handler)

       return api

    def __eq__(self, other):
       try: return self.handle.id == other.handle.id
       except: return False

    @property
    @utils.cache(512)
    def nickname(self):
       try: return unicode("@" + self.handle.screen_name)
       except: utils.error("Cannot return nick for handle %r" % self.handle)

    @property
    @utils.cache(512)
    def friends(self, id=None):
       return map(type(self), self.service.GetFriends(skip_status=True))

    @property
    @utils.cache(512)
    def followers(self):
       return map(type(self), self.service.GetFollowers())

    @property
    @utils.cache(512)
    def blocks(self):
       return []
       return map(type(self), self.service.GetMutes(skip_status=True))

    @utils.cache(512)
    def breadcrumbs(self, count=2):
       try:
          recent = self.service.GetUserTimeline(user_id=self.handle.id, count=count)
          guesses = filter(None, (Twitter.locate(status) for status in recent))

          if guesses: return max(guesses, key=lambda location: location.confidence)

       except twitter.TwitterError:
          utils.log("Cannot get user timeline for %r" % self.handle.id)

    @classmethod
    @utils.cache(512)
    def locate(cls, status):
       try: text = status.full_text or status.text
       except: text = status.text

       if text.startswith("RT "): return

       if status.place:
          # .bounding_box for Tweepy, dict for Twitter-Python
          try: location = where.Coords(where.Coords.center(where.Coords.fromgeometry(status.place.bounding_box)))
          except: location = where.Coords(where.Coords.center(where.Coords.fromgeometry(status.place['bounding_box'])))
          if location.radius < 100: return location

       if status.coordinates:
          return where.Coords(where.Coords.fromgeojson(status.coordinates), confidence=0.9)

       for name, location in cls.locations.items():
          full, partial = name.lower(), name.lower().split(" ")[0].strip(",()")

          if len(full) > 4 and full in text.lower(): return location.coords
          if len(partial) > 4 and partial in text.lower(): return location.coords

       else:
          utils.log("Locating tweet based on city")
          return where.city(text, language=status.lang)

    @property
    @utils.cache(512)
    def coords(self):
       def validate(location):
          bogus = {u"none", u"worldwide", u"somewhere", u"earth", u"moon", u"earthquake", u"here", u"based in paris, works globally"}

          if self.language == 'en':
             try:
                tokens = location.split()
                tokens.append(us.states.lookup(tokens.pop()).name)
                tokens.append("US")
                location = " ".join(tokens)
             except: pass

          if (location and location.lower() not in bogus) and (re.match(r"[\s\w]{4,}", location or "", re.UNICODE)): return location

       if self.breadcrumbs():
          return self.breadcrumbs()
       elif validate(self.handle.location):
          location = self.locations.get(self.handle.location) or where.locate(validate(self.handle.location), language=self.language)

          if location:
             self.locations[self.handle.location] = location
             return location.coords


    @property
    @utils.cache(2048)
    @profile
    def handle(self):
       conversions = [
          lambda id: twitter.models.User.NewFromJsonDict(id),
          lambda id: self.service.GetUser(user_id=int(id)),
          lambda id: self.service.GetUser(screen_name=id),
          lambda id: id,
       ]

       for attempt in range(2):
          for conversion in conversions:
             try:
                result = conversion(self.id)
                if result: return result
             except: continue

          time.sleep(5)

       raise RuntimeError("Couldn't convert Twitter ID %r" % self.id)

    def __format__(self, type):
       try:
          if type == 'id': return str(self.handle.id)
          if type == 'name': return str(self.nickname)
          return "Twitter({name}/{id})".format(name=self.nickname, id=self.handle.id)
       except:
          return str(self.id)

    @property
    @utils.cache(512)
    def language(self):
       # This is no longer supported by the Twitter API, which will just return null, so we'll just return 'en'
       return 'en'
#       utils.log("Language of {handle} is {lang}".format(handle=self.nickname, lang=self.handle.lang))
       return str(self.handle.lang or 'en')[:2]

    previous = None

    def submit(self, title, details, coords, tag, pings, urgent=False):
       pings = [ping for ping in pings if ping.startswith("#") or ping.startswith("@")]

       if self.id:
          text = self.collate(title, details) if not self.thread(tag) else details
          try:
             self.service.PostDirectMessage(user_id=self.handle.id, text=text)
          except:
             # Not even sure if sending to self.id makes any sense, but let's just see if I get these exceptions
             utils.error("WARNING: Unlikely to have sent tweet to ID: %s" % tweet)
             self.service.PostDirectMessage(user_id=self.id, text=text)
          return title
       else:
          latitude, longitude = coords.latitude if coords else None, coords.longitude if coords else None

          for max in range(270, 130, -15):
             try:
                tweet = unicodedata.normalize('NFC', unicode(details or title))[:max]
                previous = self.thread(tag).id if not urgent and self.thread(tag) else None
                return self.service.PostUpdate(" ".join([tweet] + list(pings)[:max/54]), latitude=latitude, longitude=longitude, in_reply_to_status_id=previous)
             except:
                utils.error("WARNING: tweet not accepted: %s" % tweet)
                time.sleep(2 if urgent else 5)
          else:
             raise RuntimeError("Tweet not accepted: %s" % tweet)

    def redact(self, thread, tag):
       if thread: self.service.DestroyStatus(thread)

    def receive(self, channels=[], users=[]):
       self.stream = self.service.GetStreamFilter(follow=users, track=channels)
       return self.stream
#       return self.stream.stream.statuses.filter.post(track=channels, follow=users).stream()

    def stream(self, callback):
       return tweepy.Stream(auth=self.tweepy.auth, listener=callback)
