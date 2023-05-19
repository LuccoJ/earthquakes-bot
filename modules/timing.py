"""
timing.py - Modules for measuring time taken by various activities, and simple profiling

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

import timeit
from threading import Lock
from copy import copy
from qualname import qualname
from functools import wraps
from random import gauss

from modules import utils

class Stopwatch(object):
    timer = timeit.default_timer
    lock = Lock()

    def __init__(self, description=None, long=0.0):
       self.description = description
       self.starts = []
       self.elapsed, self.partial = 0.0, 0.0
       self.count = 0
       self.long = long
       self.running = False
       self.exception = None

    def __enter__(self):
       #if self.running: utils.log("WARNING: {timer.description} is being started while already running".format(timer=self))
       with self.lock:
          self.starts.append(self.timer())
          self.running = True
          return self

    def __exit__(self, exc_type, exc_val, exc_tb):
       with self.lock:
          self.partial = self.timer() - self.starts.pop()
          self.elapsed += self.partial
          self.count += 1
          self.exception = exc_val
          self.running = False

          if self.description and self.partial > self.long: self.log()

    def __lt__(self, other):
       return bool(self.average < other.average)

    def __repr__(self):
       try: return "Stopwatch({description}, elapsed={elapsed}, average={average})".format(description=str(self.description), elapsed=self.elapsed, average=self.average)
       except: return "Stopwatch(not printable)"

    @property
    def average(self):
       return (self.elapsed / self.count) if self.count else self.elapsed

    def log(self):
       utils.log("{t.description}: {t.count} times in {t.elapsed:.3f}s (average {t.average}, last {t.partial:.5f}s raised {t.exception})".format(t=self))

    def __format__(self, style):
       return format(self.elapsed, style or ".4f")


class Balancer(object):
   class Exhausted(Exception): pass

   def __init__(self, choices, long=10):
      self.name = "Load balancer for {choices}".format(choices=choices)
      self.timings = {choice: Stopwatch("Load balancer for {choice}".format(choice=choice), long=long) for choice in choices}

   def __call__(self, name=None, attempts=1024, timeout=3600, roundrobin=True):
      clone = copy(self)
      clone.name = name or self.name
      clone.attempts = attempts
      clone.timeout = timeout
      clone.roundrobin = roundrobin
      clone.timings = self.timings.items()

      return clone

   def __enter__(self):
      if self.attempts <= 0: raise self.Exhausted("Load balancer out of tries")
      if self.timeout <= 0: raise self.Exhausted("Load balancer timed out")
      if not self.timings: raise self.Exhausted("Load balancer out of options")

      criterion = lambda (choice, timer): timer.elapsed if self.roundrobin else gauss(timer.average, timer.average*0.2)

      self.timings.sort(key=criterion, reverse=True)
      self.choice, self.stopwatch = self.timings.pop()
      self.stopwatch.__enter__()

      utils.log("Load balancer {choice}: {stopwatch} chosen".format(choice=self.choice, stopwatch=self.stopwatch))

      return self.choice

   def __exit__(self, *args):
      self.stopwatch.__exit__(*args)

      self.timeout -= self.stopwatch.partial
      self.attempts -= 1

      if self.stopwatch.exception:
         utils.log("{t.description} failed with {t.exception!r} after {attempts} attempts, {t.elapsed} s total".format(t=self.stopwatch, attempts=self.attempts))
         self.stopwatch.elapsed = (self.stopwatch.elapsed+1.0)*2.0
      else:
         utils.log("{t.description} succeeded after {attempts} attempts, {t.elapsed} s total".format(t=self.stopwatch, attempts=self.attempts))


def profile(function):
    @wraps(function)
    def wrapper(*args, **kwargs):
        period = 100

        try: name = str(qualname(function))
        except: name = function.__name__
        timer = profile.timings.setdefault(name, Stopwatch("Profiling {function}".format(function=name), long=5.0))

        try:
           with timer: result = function(*args, **kwargs)
        finally:
           if not timer.count % period:
              utils.log("Profile: Function {function} took {t.elapsed}s for {t.count} calls, last was {t.partial}".format(t=timer, function=name))
              #utils.log("Profile: Active threads: {count}".format(count=len(threading.enumerate())))

        return result

    return wrapper

profile.timings = {}
