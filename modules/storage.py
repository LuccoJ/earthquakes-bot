"""
storage.py - Small wrapper to Python's persistent storage library stuff

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

import pickle
import shelve
import time
import threading
import os
from collections import MutableMapping

def path(bot, file):
   directory = os.path.realpath(os.path.expanduser(bot.config.data_dir) if hasattr(bot.config, 'data_dir') else 'data')
   path = os.path.join(directory, "{file}.db".format(file=file))
   return path

def stringify(key):
   strategies = [
      (lambda input: input, lambda input, output: output == str(output)),
      (repr,                lambda input, output: output != object.__repr__(input)),
      (str,                 lambda input, output: output != object.__str__(input)),
      (hash,                lambda input, output: output != object.__hash__(input)),
      (pickle.dumps,        lambda input, output: True),
   ]

   def encode(item, strategy):
      encoder, checker = strategy
      encoded = encoder(item)

      if checker(item, encoded): return encoded
      else: raise RuntimeError("Bad encoding")

   for strategy in strategies:
      try: return str(encode(key, strategy))
      except: continue

   raise RuntimeError("Cannot encode a DB key from object")

class Database(MutableMapping):
   period = 60

   def __init__(self, file, writeback=False):
      self.items = shelve.open(file, protocol=pickle.HIGHEST_PROTOCOL, writeback=bool(writeback))
      self.lock = threading.Lock()

      if writeback:
         if writeback is not True: self.period = float(writeback)
         threading.Thread(target=lambda: self.sync(self.period)).start()

   def __del__(self):
      self.close()

   def __setitem__(self, key, value):
      with self.lock: self.items[stringify(key)] = value

   def __getitem__(self, key):
      with self.lock: return self.items[stringify(key)]

   def __delitem__(self, key):
      with self.lock: del self.items[key]

   def __contains__(self, key):
      with self.lock: return True if stringify(key) in self.items else False

   def __len__(self, key):
      with self.lock: return len(self.items)

   def __iter__(self):
      with self.lock: return iter(self.items)

   def close(self):
      self.items.close()
      self.items = None

   def sync(self, period=None):
      while self.items:
         if period: time.sleep(period)
         with self.lock: self.items.sync()
         if not period: break
