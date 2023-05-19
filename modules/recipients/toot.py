#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
toot.py - Send toots on Mastodon (DM not supported)

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

import mastodon
import unicodedata
import time

from modules import utils
from modules import where

class Mastodon(Recipient):
    protocol = "mastodon"
    style = 'short'
    priority = -10

    paragraph = "\n\n"

    maxlength = 270

    semaphore = utils.LazySemaphore(8)

    def initialize(self, service, instance_url=None, client_key=None, client_secret=None, access_token=None, url=None):
       return mastodon.Mastodon(api_base_url=instance_url, client_id=client_key, client_secret=client_secret, access_token=access_token)

    def __eq__(self, other):
       try: return self.handle.id == other.handle.id
       except: return False

    @property
    def nickname(self):
       return unicode(self.handle.acct)

    @property
    @utils.cache(32)
    def friends(self, id=None):
       return map(type(self), self.handle.friends(count=200))

    @property
    @utils.cache(32)
    def followers(self):
       return map(type(self), self.handle.followers(count=200))

    @property
    @utils.cache(32)
    def blocks(self):
       return map(type(self), self.service.blocks(count=200))

    @classmethod
    @utils.cache(32)
    def locate(cls, status):
       return where.city(status.text)

    @utils.cache(32)
    def breadcrumbs(self, count=10):
       with self.semaphore.optional("Too many Mastodon calls"), self.semaphore:
          try:
             recent = self.service.timeline(limit=count)
             guesses = filter(None, (self.locate(status) for status in recent))

             if guesses: return max(guesses, key=lambda location: location.confidence)
          except: utils.error("Cannot get user timeline for %r" % self.handle.id)

    @property
    @utils.cache(32)
    def coords(self):
       if self.breadcrumbs(): return self.breadcrumbs()

    @property
    @utils.cache(32)
    def handle(self):
       try:
          return self.id if isinstance(self.id, dict) else self.service.account_search(self.id)[0] if self.id else self.service.account_verify_credentials()
       except:
          utils.error("Mastodon is rate limiting!")

    def __format__(self, type):
       if type == 'id': return str(self.handle.id)
       if type == 'name': return str(self.nickname)
       return "Mastodon({name}/{id})".format(name=self.nickname, id=self.id)

    @property
    @utils.cache(32)
    def language(self):
       return str(self.handle.lang or 'en')[:2]

    def submit(self, title, details, coords, tag, pings, urgent=False):
       pings = [ping for ping in pings if ping.startswith("@") or ping.startswith("#")]

       mode, mentions = ('direct', "@"+self.nickname) if self.id else ('public', " ".join(pings))

       words = unicode(details or title).split(" ")

       # Do it locally with a hardcoded limit because hammering the server later is just silly
       for limit in range(len(words), 5, -1):
          words = words[:limit]
          if len(unicodedata.normalize('NFC', " ".join(words))) < 500: break

       # Do the silly thing anyway, just in case, although in practice it shouldn't happen with the above
       for limit in range(len(words), 5, -1):
          try:
             toot = unicodedata.normalize('NFC', " ".join(words[:limit]))
             return self.service.status_post(" ".join([mentions, toot] if mode =='direct' else [toot, mentions]), visibility=mode).id
          except:
             utils.error("WARNING: toot not accepted, may be too long (%r): %s" % (len(toot), toot))
             time.sleep(2 if urgent else 5)
       else:
          raise RuntimeError("Toot not accepted: %s" % toot)

    def redact(self, thread, tag):
       if thread: self.service.status_delete(thread)

    def stream(self, callback):
       return self.service.stream_public(callback, run_async=True, reconnect_async=True)

    def __repr__(self):
       return "{cls}({id})".format(cls=type(self).__name__, id=self.nickname)
