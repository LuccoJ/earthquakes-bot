"""
utils.py - Brainstorm Utilities, some of which are used by the earthquakes (alerts) module
Copyright 2013-2022, Lorenzo J. Lucchini, ljlbox@tiscali.it

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""

"""
General utilities file that predates the earthquake stuff, but some of
it is used by the earthquake stuff. This file has been pruned a little
but may contain stuff that has nothing to do with earthquakes, and that
may have to be removed or fixed before it actually works.
"""

import re
import random
import requests
import inspect
import sys
import collections
import itertools
import os
import warnings
import traceback
import time
import threading
import Queue
from weakref import WeakValueDictionary
from contextlib import contextmanager
from StringIO import StringIO
from PIL import Image, ImageFilter
from cachecontrol import CacheControl
from cachecontrol.heuristics import BaseHeuristic
from cachetools.func import lfu_cache as cache
from threading import RLock
from bs4 import BeautifulSoup
from difflib import get_close_matches
from functools import wraps

try: import natlang
except: print "Could not import natlang module"

from modules import pdftitle

from modules.when import When

FILTER_URL = re.compile(r'(?:https?://|www.)\S+\.\S+')
FILTER_NICK = re.compile(r'([]\w[^|{}-]{1,32}).*')
FILTER_CHANNEL = re.compile(r'[#&+!]\w{0,49}')
FILTER_IP = re.compile('%s\.%s\.%s\.%s' % ((r'[1-2]?[0-9]?[0-9]',) * 4))
FILTER_TEXT = re.compile(r'[\w\s!"#%&/()=?\',.;:<>-]+', re.UNICODE)

ERROR_FILTER = "the command line provided is invalid"
ERROR_EMPTY = "no command line was provided"
ERROR_HISTORY = "the sought line was not found in message history"
ERROR_URL = "the URL could not be loaded"


timings = {}

class Commutative(object):
   def __radd__(self, other): return self + other
   def __rmul__(self, other): return self * other


class Rejecter(object):
    class Rejection(Exception): pass


class Shadowable(object):
    shadows = WeakValueDictionary()

    def __new__(cls, *args, **kwargs):
       hashable = cls, tuple(args), tuple(kwargs.items())

       try: return cls.shadows[hashable]
       except: new = super(Shadowable, cls).__new__(cls, *args, **kwargs)

       try: cls.shadows[hashable] = new
       except: pass

       return new


class LazySemaphore(Rejecter):
    class SemaphoreError(Exception): pass

    def __init__(self, count=1):
       self.semaphore = threading.Semaphore(count)

    def __enter__(self):
       if self.semaphore.acquire(blocking=False): return True
       else: raise LazySemaphore.Rejection("Semaphore full")

    def __exit__(self, error, *args):
       self.semaphore.release()

    @contextmanager
    def optional(self, message="Semaphore full"):
       try: yield
       except LazySemaphore.Rejection: log(message)


class WorkQueue(Queue.PriorityQueue, object):
   timeout = None

   def __iter__(self):
      return iter(self.expect, StopIteration)

   def expect(self):
      try: return self.get(timeout=self.timeout)
      except Queue.Empty: return StopIteration

   def close(self):
      self.put(StopIteration)


class Worker(Rejecter):
   period = 0.1
   pause = 0.01

   def __init__(self, processor=None):
      self.process = processor or self.process

   def start(self, input=None, output=None, timeout=3600, size=512, threads=1):
      def run(input, output):
         for item, origin in input:
            if item is None: continue

            try:
               if input.qsize() > size/2:
                  log("WARNING: {worker.__name__}'s input queue {queue.__name__} is half full!".format(worker=type(self), queue=type(input)))
               if output.qsize() > size/2:
                  log("WARNING: {worker.__name__}'s output queue {queue.__name__} is half full!".format(worker=type(self), queue=type(output)))
            except AttributeError:
               # Input and output are not necessarily queues
               pass

            try:
               for result in self.process(item, origin):
                  if result is None: continue

                  output.put((result, self), block=False)
                  time.sleep(self.pause)
                  self.pause *= 0.8
            except Worker.Rejection:
               log("{worker} declined to process input".format(worker=type(self)))
            except Queue.Full:
               log("WARNING: {worker.__name__}'s output queue {queue.__name__} was full!".format(worker=type(self), queue=type(output)))
            except Queue.Empty:
               log("WARNING: {worker.__name__}'s input queue {queue.__name__} timeout!".format(worker=type(self), queue=type(input)))
               break
            except Exception:
               error("WARNING: {worker.__name__} could not process input".format(worker=type(self)))

         log("WARNING: {worker.__name__} terminated!".format(worker=type(self)))

      self.input, self.output = input or WorkQueue(maxsize=size), output or WorkQueue(maxsize=size)

      self.threads = range(threads)

      for index in self.threads:
         self.threads[index] = threading.Thread(name="{worker.__name__} {index}".format(worker=type(self), index=index), target=run, args=(self.input, self.output))
         self.threads[index].start()

      log("Started {worker}".format(worker=type(self)))

#   def enqueue(self, item, origin=None, priority=0, *args, **kwargs): self.input.put(((priority, item), origin), *args, **kwargs)

   def put(self, *args, **kwargs): self.input.put(*args, **kwargs)

   def get(self, *args, **kwargs): return self.output.get(*args, **kwargs)[1]

   def finish(self):
      for thread in self.threads: self.input.put(StopIteration)

   def __iter__(self): return iter(self.output)

   @property
   def running(self):
      try: return any(thread.isAlive() for thread in self.threads)
      except: return False

   def ticker(self, seconds=None):
      for index in itertools.count():
         def wait(portion): time.sleep((seconds or self.period) * portion)

         portion = random.random()

         wait(portion)
         yield (0, index), self
         wait(1.0 - portion)


class Locking(object):
   locks = {}

   def __new__(cls, object, classwise=False):
      for name, callable in inspect.getmembers(object, inspect.isroutine):
         lock = cls.locks[type(object) if classwise else id(object)] = RLock()
         try:
            setattr(object, name, cls.decorator(callable, lock))
         except AttributeError as error:
            log("Can't set attribute %r (%r) of %r because %r" % (name, callable, object, error))

      cls.locks[object] = RLock()

      return object

   @staticmethod
   def decorator(method, lock):
      @wraps(method)
      def wrapped(*args, **kwargs):
         with lock: return method(*args, **kwargs)

      return wrapped


class API(object):
   def __init__(self, resource, format='json', method='get'):
      self.resource = resource.strip("/")
      self.format = format
      self.method = method
      self.parameters = {}

   def request(self, endpoint, **params):
      full = self.parameters.copy(); full.update(params)
      response = web.get(self.resource + "/" + endpoint.strip("/"), params=full)

      if self.format == 'json': return response.json()
      else: return response


class MinimumHeuristic(BaseHeuristic):
   minimum = 30

   def update_headers(self, response):
      current = requests.utils.parse_dict_header(response.headers.get('Cache-Control', {})).get('max-age', 0)
      return {'cache-control' : 'max-age=%s' % max(current, self.minimum)}


def match(string1, string2):
   if string1 is None or string2 is None: return False

   if string1 == string2 or string1.lower() == string2.lower() or string1.upper() == string2.upper():
      return True
   else:
      return False

def html(data):
   with warnings.catch_warnings():
      warnings.simplefilter("ignore")
      return BeautifulSoup(data, 'lxml')

def strip(data, sep=' '):
   if not data: return data
   else: return html(data).getText(separator=sep, strip=True)

def similar(text, possibilities, n=3, cutoff=0.7):
   def simplify(text): return text.strip(" ,.;:?!").lower()

   return get_close_matches(simplify(text), [simplify(possibility) for possibility in possibilities], n, cutoff)

def clip(quantity, minimum, maximum):
   return max(minimum, min(maximum, quantity))

def exceeds(quantities, threshold):
   for quantity in iter(quantities):
      try:    total += quantity
      except: total = quantity
      if total > threshold:
         return True

   return False

def database(bot, file):
   directory = os.path.realpath(os.path.expanduser(bot.config.data_dir) if hasattr(bot.config, 'data_dir') else 'data')
   path = os.path.join(directory, "%s.db" % file)
   log("Opening %s" % path)
   return path

def unzip(zipped):
   return zip(*zipped)


def setup(bot):
   bot.chat = BotMessaging(bot)
   web.headers.update({'user-agent': bot.nick})


class Message(object):
   def __init__(self, sender=None, nick=None, text=None, timestamp=None):
      self.timestamp = timestamp or When.now()
      self.sender = sender
      self.nick = nick
      self.text = text

   def __unicode__(self):
      return "\x1d(%s)\x1d <%s> %s" % (self.timestamp.format('human'), self.nick, self.text)


class History(object):
   def __init__(self, size=1024):
      self.history = collections.deque(maxlen=size)

   def write(self, sender=None, nick=None, text=None, timestamp=None):
      self.history.append(Message(sender, nick, text, timestamp))

   def find(self, nick=None, channel=None, filter=None):
      output = []

      try: filter = re.compile(filter or r'.*', re.IGNORECASE + re.UNICODE)
      except: pass

      for entry in reversed(self.history):
         if nick and not match(nick, entry.nick): continue
         if channel and not match(channel, entry.sender): continue
         try:
            assert filter.search(entry.nick).group(0) and not nick
         except:
            try: filter.search(entry.text).group(0)
            except: continue

         output.append(entry)

      return output


class BotMessaging:
   max_length = 510

   def __init__(self, bot):
      self.bot = bot
      self.history = History()
      self.remainder = {}

   class Parsed:
      def __init__(self, nick=None, text=None, input=None, output=None, engines=None, max=4):
         self.nick = nick
         self.text = text
         self.inputs = input[:max] if isinstance(input, (list, set, tuple)) else [input]
         self.outputs = output[:max] if isinstance(output, (list, set, tuple)) else [output]
         self.engines = engines[:max] if isinstance(engines, (list, set, tuple)) else [output]
         self.history = False
         self.error = None
         self.format('linguistlist')
         self.filter(r'^.*$')

      @property
      def input(self):
         return self.inputs[0] if len(self.inputs) > 0 else None

      @property
      def output(self):
         return self.outputs[0] if len(self.outputs) > 0 else None

      def filter(self, filter):
         self.regexp = filter
         self.match = re.search(self.regexp, self.text)

         if not self.match: return self.fail(ERROR_FILTER)
         return self

      def format(self, type):
         self.inputs = [natlang.langcode(original, type) for original in self.inputs]
         self.outputs = [natlang.langcode(original, type) for original in self.outputs]
         return self

      def guess(self, input=None, output=None):
         from modules import engines

         if not self.input:
            self.inputs = [None]

            identifier = engines.LanguageIdentifier(self.text)
            guesses = identifier.process().merge().output

            if len(guesses) > 0:
               self.inputs[0], score, sources = guesses[0]
            if len(guesses) > 1 and natlang.langcode(self.input) == natlang.langcode(self.output):
               self.inputs[0], score, sources = guesses[1]

            log("Guessing language used in '%s' is %s" % (self.text, natlang.langcode(self.input, 'name')))

         if not self.input: self.inputs = [input]
         if not self.output: self.outputs = [output]

      def fail(self, error=None):
         self.error = error
         if self.error: log("Error parsing '%s' with '%s' (%s)" % (self.text, self.regexp, self.error))
         return self


   def message(self, input, before, items=[], after="", sep=u" — ", split=True, cmd="PRIVMSG", prompt=None, addressee=None, target=None):
      channel = target or (input.sender if input else addressee)
      addressee = ', '.join(addressee) if isinstance(addressee, (list, tuple, set)) else addressee
      addressee = addressee if addressee is not None else (input.nick if input else None)

      if not prompt: prompt = " [... want %smore?]" % (self.bot.config.prefix)
      if not items: items = ['']

      if not isinstance(items, (list, set, tuple)): items = [items]
      items = [unicode(item) for item in items]

      before, after = unicode(before), unicode(after)

      if before and not before.endswith(" "): before = before + " "
      if after and not after.startswith(" "): after = " " + after

      if cmd.upper() == "CTCP":
         cmd, before, after = ("PRIVMSG"), ("\x01" + before), (after + "\x01")
      elif addressee and not match(addressee, channel):
         before = "%s, %s" % (addressee, before)
      else:
         before = before[:1].upper() + before[1:]

      overhead = ":%s!%s@%s %s %s :" % (self.bot.nick, self.bot.user, ' '*63, cmd, channel)

      output = before + " (no items) " + after, []

      pending = None

      for parts, sep in [(items, sep), (items[0].split(' '), ' '), (items[0], '')]:
         candidate = before + after
         for index, part in enumerate(parts, 1):
            candidate = u"{pre}{items}{prompt}{post}".format(pre=before, items=sep.join(parts[:index]), prompt=(prompt if index < len(parts) else ''), post=after)
            if len((overhead + candidate).encode('utf-8')) > self.max_length: break
            output, pending = candidate, parts[index:]

         if index > 1: break
      else:
          # In some edge case I can't be bothered to identify, the for doesn't output a thing, and so output is a tuple when it shouldn't be
          try: output, _ = output
          except: pass

      if pending: self.remainder[channel.lower()] = pending, items, sep

      log("output: %r" % (output,))

      if len(output.encode('utf-8')) > self.max_length: raise Exception("Message too long")
      if len(output.encode('utf-8')) < 1: return log("Not sending empty message")

      if split or not pending: self.bot.write([cmd, channel], output)
      return pending


   def more(self, input):
      channel = input.sender.lower()
      if channel in self.remainder:
         pending, full, sep = self.remainder[channel]
         try: link = u' → %s' % pastebin(u"\n".join(full))
         except: link = None
         self.message(input, "[...] ", pending, link, sep=sep, prompt=" [...]")
         del self.remainder[channel]
         return True

      return False

@cache(10)
def shorten(url):
   try:
      shorturl = web.get('http://mndr.xyz/rest/v2/short-urls/shorten', headers={'X-Api-Key': shlink_key}, params={'format': "text", 'longUrl': url}).text
      return shorturl if len(shorturl) + 32 < len(url) and not shorturl.startswith("Error") else url
   except:
      return url


def log(message):
   frame, file, line, function, context, index = inspect.stack()[1]
   caller = inspect.getmodule(frame).__name__

   print "%s/%s (%s): %s" % (caller, function, threading.current_thread().name, message)
   sys.stdout.flush()

   return False

def error(string="exception"):
   trace = traceback.format_exc()
   log("WARNING: %s in %s (%s)" % (string, threading.current_thread().name, trace))

def trace(string="stack trace"):
   trace = ''.join(traceback.format_stack())
   log("%s (%s)" % (string, trace))

# Work around some broken website SSL
requests.packages.urllib3.util.ssl_.DEFAULT_CIPHERS += 'HIGH:!DH:!aNULL'
try: requests.packages.urllib3.contrib.pyopenssl.DEFAULT_SSL_CIPHER_LIST += 'HIGH:!DH:!aNULL'
except AttributeError: pass

web = requests.Session()
web.headers.update({'user-agent': 'my-bot'})
web = CacheControl(web, heuristic=MinimumHeuristic())
