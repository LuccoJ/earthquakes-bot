#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
recipient.py - Generic message recipient with logic that applies to all the subclasses

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

import re
import time
from threading import Timer, RLock
from requests.utils import urlparse
from cachetools import LFUCache
from unicodedata import category
import mistune

from modules import utils
from modules.timing import profile


class UnrecognizedError(Exception):
    pass


class Renderer(mistune.Renderer):
    def __call__(self, text):
       return mistune.Markdown(renderer=self).render(text)


class Recipient(utils.Shadowable):
    protocol = None
    style = 'machine'
    throttle = 0.1
    renderer = None
    bold, italic, underline, paragraph, hashtag, colors = "", "", "", "\n\n", "", False
    services = {}
    credentials = None
    priority = 0

    def collate(self, *lines):
       return self.paragraph.join(filter(None, lines))

    @profile
    def __init__(self, id=None, server=None, style=None, icons=True):
       self.datalock, self.messagelock = RLock(), RLock()
       self.previous, self.time = (None, None), time.time()

       self.id = id
       self.threads = LFUCache(maxsize=256)
       self.server = server or self.protocol

       try: self.service = self.services[self.server] = self.services.get(self.server) or self.initialize(self.server, **self.credentials.get(self.server, {}))
       except: self.service = None

       self.style = style or self.style
       self.icons = icons

       if not self.service: utils.log("WARNING: Could not initialize service for {self}".format(self=self))

    def __eq__(self, other):
       try: return type(self.handle) == type(other.handle) and (self.handle, self.server) == (other.handle, other.server)
       except: return False

    def __lt__(self, other):
       return self.priority < other.priority

    @property
    def handle(self):
       return self.id

    @property
    def nickname(self):
       return self.id

    def thread(self, tag, new=None, search=True):
       if new:
          self.threads[tag] = new

       if search and not self.threads.get(tag):
          try: self.threads[tag] = self.search(tag)
          except: utils.error("Could not find thread for {tag} on {recipient}".format(tag=tag, recipient=self))

       return self.threads.get(tag)

    def search(self, tag):
       return None

    def resolve(self, uri):
       if not uri or (self.protocol and urlparse(uri).scheme != self.protocol): return

       id, __, service = urlparse(uri).netloc.partition('@')
       return (id, service)

    def receive(self, callback, channels=[], users=[]):
       raise NotImplementedError("This recipient cannot receive")

    def send(self, title=None, details=None, coords=None, tag=None, pings=[], urgent=False):
       if not self.service:
          utils.log("WARNING: Cannot send message because {protocol} service is not initialized".format(protocol=self.protocol))

       def convert(string, icons=True):
          if not string: return ""
          string = unicode(string)
          string = string.replace("\x02", self.bold)
          string = string.replace("\x1d", self.italic)
          string = string.replace("\x1f", self.underline)
          string = string.replace(u"＃", self.hashtag)
          string = string if self.colors else re.sub(r"\x03\d\d|\x03", "", string)
          string = string if icons else u"".join(character for character in string if category(character) not in ['Cn'])
          return string

       def dispatch(title, details, coords, tag, pings, urgent=False):
             try:
                with self.messagelock:
                   old = self.thread(tag, search=not urgent)
                   new = self.submit(title, details, coords, tag, pings, urgent)
                   self.thread(tag, new)
                   utils.log("Created thread {thread} about {tag} in {recipient}".format(thread=new, tag=tag, recipient=self))

                if old or tag:
                   try:
                      time.sleep(600)
                      self.redact(old, tag)
                      utils.log("Redacted {thread} about {tag} in {recipient}".format(thread=old, tag=tag, recipient=self))
                   except Exception as error:
                      utils.log("WARNING: Could not redact thread {thread} tagged {tag} ({error})".format(thread=old, tag=tag, error=error))

             except:
                utils.error("Could not dispatch message %r with tag %r, handle %r, service %r" % (details, tag, self.handle, self.service))

       if not details: return
       title, details = convert(title, icons=self.icons), convert(details, icons=self.icons)

       with self.datalock:
          now = time.time()
          data = (title, details, coords, tag, pings, urgent)
          if data == self.previous:
             utils.log("Not sending {data}: just sent before!".format(data=data))
             return

          utils.log("Sending to {recipient} about {tag}: {content}".format(recipient=self, tag=tag, content=data))

          Timer(self.throttle*(0.1 if (now - self.time > self.throttle) else 0.5 if urgent else 1.0), dispatch, args=data).start()

          self.previous, self.time = data, now

    def submit(self, title, details, coords, tag, pings, urgent=False):
       raise NotImplementedError("Subclasses should know how to do this for their protocol")

    def redact(self, thread, tag):
       pass

    def __str__(self): return str(self.id)

    def __repr__(self): return "{cls}({id!r})".format(cls=type(self).__name__, id=self.id)

    def __format__(self, style): return "{cls}({nick})".format(cls=type(self).__name__, nick=self.nickname)

    @classmethod
    def bot(cls, phenny):
       if not phenny: utils.log("WARNING: No bot specified!")

       phenny.config.credentials['irc']['bot'] = phenny
       cls.credentials = phenny.config.credentials


class URI(Recipient):
    def __new__(cls, uri):
       id, _, service = urlparse(uri).netloc.partition('@')
       return (id, service)

       for candidate in Recipient.__subclasses__():
          if candidate.protocol and urlparse(uri).scheme != candidate.protocol: continue
          id, __, service = urlparse(uri).netloc.partition('@')

          if id or service: return candidate(id, service)

       raise UnrecognizedError
