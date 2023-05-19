"""
reddit.py - Create threads on Reddit and update them with earthquake updates (DM not supported)

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

import praw
import time
from modules.when import When
from modules import utils

class Reddit(Recipient):
    protocol = "reddit"
    throttle = 10
    style = 'fixed'
    bold, italic, paragraph = "**", "*", "\n\n"
    signature = "This post will be updated with any new data. Contact /u/LjLies for information about this bot."
    priority = 10

    target = None

    def initialize(self, service, **credentials):
       return praw.Reddit("Brainstorm")

    @property
    @utils.cache(32)
    def handle(self):
       prefix, _, id = self.id.partition("/")
       return self.service.subreddit(id) if prefix == 'r' else self.service.live(id) if prefix == 'live' else None

    def search(self, tag):
       return next(post for post in self.handle.new(limit=10) if tag in post.title and time.time() - post.created < 6*3600)

    def submit(self, title, details, coords, tag, pings, urgent=False):
       message = "> {details}\n\n^{time:machine@UTC}".format(details=details, time=When.now())

       if type(self.handle) is praw.models.Subreddit:
          try:
             thread = self.thread(tag) if not urgent else None

             if not thread: raise RuntimeError("No thread")

             utils.log("Found thread %r" % thread)

             try:
                text = thread.selftext
                replies = thread.comments
             except:
                text = thread.body
                replies = thread.replies

             if details in text or any(details in comment.body for comment in replies):
                return thread

             try:
                #text = text.replace("> ", "> ~~", 1).replace("\n\n^", "~~\n\n^", 1)
                return thread.edit(self.collate(message, text))
             except:
                return thread.reply(message)

          except:
             return self.handle.submit(title, selftext=message)

       elif type(self.handle) is praw.models.LiveThread:
          try: self.thread(tag).contrib.strike()
          except: utils.log("Could not strike Reddit Live entry for {tag} ({thread})".format(tag=tag, thread=self.thread(tag)))

          sent = self.handle.contrib.add(details)

          utils.log("SENT: type %r, %r" % (type(sent), sent))

          time.sleep(0.5 if urgent else 1)
          sent = next(self.handle.updates(limit=1))
          if sent.author == self.service.user.me() and details in sent.body: return sent

       else:
          utils.log("Unknown reddit type %s" % type)

    def redact(self, thread, tag):
       if thread and thread.stricken: thread.contrib.remove()
