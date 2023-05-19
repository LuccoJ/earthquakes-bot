"""
file.py - Save messages to a file instead of sending to a real recipient

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

from modules.when import When

class File(Recipient):
    protocol = "file"
    throttle = 1
    style = 'machine'
    bold, italic, underline, colors = "", "", "", False
    priority = 20

    def initialize(self, service):
       return True

    def submit(self, title, details, coords, tag, pings, urgent=False):
       open(self.id, 'a').write("%s %-35s %-65s %s\n" % (When.now(), coords, title, details))
