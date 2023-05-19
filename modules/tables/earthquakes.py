#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
earthquakes.py - Regular expressions identifying many earthquake tweets and RSS entries

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

from modules import utils

def parse(text, full=False):
   def groups(expression):
      result = expression.search(text).groupdict() or expression.search(text.decode('utf-8')).groupdict()
      return result if not full else (result, expression.pattern)

   text = unicode(text).replace(u"\u00A0", u"")

   for pattern in blacklist:
      if pattern.search(text): return

   for expression, timezone, country in patterns:
      try: return groups(expression), timezone, country
      except AttributeError: continue


blacklist = [
   r"Alert for HighWaves",
   r"Tsunami Information Statement",
   r"Final Tsunami Threat",
   r'Tropical Depression',
   r'Tropical Cyclone',
   r'Cyclones Tropicaux',
   r'Storm Warning',
   r'KT WINDS',
   u"降灰予報",
   u'第\d報',
]

for index, expression in enumerate(blacklist):
   blacklist[index] = re.compile(expression, re.IGNORECASE | re.UNICODE | re.DOTALL)

patterns = [
   (u'(SWIFT|Swift) ID:\d+, (?P<status>.+), Date: ?(?P<time>\d.+), Lat: ?(?P<lat>.+), Lon: ?(?P<lon>.+), Depth: ?(?P<depth>[\d.]+) km, (?P<magtype>M\w*): (?P<mag>[\d.]+)', 'UTC', None),
   (u'\[(?P<time>[\d:]+) UTC\] +earthquake detected at .+3 from (?P<area>.+). Download .+ (?P<link>http\S+)', 'UTC', None),
   (u'\[(?P<time>[\d:]+) UTC\] +sismo detectado a .+ de (?P<area>.+)\. Descarga .+ (?P<link>http\S+)', 'UTC', None),
   (u'\[(?P<time>[\d:]+) UTC\] +terremoto rilevato a .+ da (?P<area>.+)\. Scarica .+ (?P<link>http\S+)', 'UTC', None),
   (u'earthquake.*:.*[Ii]nfobox earthquake.*\| timestamp = (?P<time>[^+]+).*\| magnitude = (?P<mag>[\d.]+) {{M\|(?P<magtype>[^}|]+).*\| depth = {{convert\|(?P<depth>[^|]+)\|km.*location = {{Coord|(?P<lat>[^|]\|.)\|(?P<lon>[^|]\|.).*\| casualties = (?P<victims>\d+)', 'UTC', None),
   (u': (?P<time>\S+ \S+) (?P<mag>[\d.]+) .(?P<magtype>M\w*). (?P<coords>\S+ \S+) (?P<depth>[\d.]+)', 'Asia/Istanbul', None),
   (u'Yer: (?P<area>.+) / Tarih: (?P<date>.+) / Saat: (?P<time>.+) / Büyüklük: (?P<mag>[\d.]+) / Derinlik: (?P<depth>.+) Km', 'Asia/Istanbul', 'Turkey'),
   (u'Büyüklük: (?P<mag>[\d.]+) Tarih:  (?P<date>.+) Saat:  (?P<time>.+) Derinlik:  (?P<depth>.+) km .+ (?P<link>http\S+)', 'Asia/Istanbul', None),
   (u'Büyüklük : (?P<mag>[\d.]+) \((?P<magtype>\w+)\) Yer : (?P<area>.+) Tarih-Saat : (?P<date>.+), (?P<time>.+) TSİ Enlem : (?P<lat>.+) Boylam : (?P<lon>.+) Derinlik : (?P<depth>.+) km Detay : (?P<link>http\S+)', 'Asia/Istanbul', 'Turkey'),
   (u'büyüklük (?P<mag>[\d.]+) (?P<magtype>\w+) .* derinlik (?P<depth>.+)km (?P<lat>\w+) (?P<lon>\w+) .* (?P<time>\d\d:\d\d:\d\d) \+03', 'Asia/Istanbul', 'Turkey'),
   (u'Büyüklük:(?P<mag>[\d.]+) \((?P<magtype>\w+)\) Yer:(?P<area>.+) Tarih:(?P<date>.+) Saat:(?P<time>.+) TSİ Enlem:(?P<lat>.+) Boylam:(?P<lon>.+) Derinlik:(?P<depth>.+) km Detay:(?P<link>http\S+)', 'Asia/Istanbul', 'Turkey'),
   (u'Time: (?P<time>.+) Latitude: (?P<lat>.+) Longitude: (?P<lon>.+) Depth: (?P<depth>[\d.]+)km (?P<magtype>M\w*) (?P<mag>[\d.]+)', 'UTC', None),
   (u'Mag:(?P<mag>[\d.]+) \S+ km \S+ +from (?P<area>.+) Depth: ?(?P<depth>[\d.]+)km (?P<time>.+):UTC .* (?P<link>http\S+)', 'UTC', 'US'),
   (u'\d+,\d+,(?P<update>.+),\d+,\d+,\w+,(?P<time>.+),(?P<lat>.+),(?P<lon>.+),(?P<area>.+),(?P<depth>.+),(?P<mag>.+),\d+,\d+,\d+', 'UTC+9', None),
   (u'EQ M(?P<mag>[\d.]+) \[(?P<status>.+)\].*Hora Chilena. (?P<time>\d.+) .UTC..*\((?P<coords>.+,.+)\).*(?P<link>http\S+)', 'UTC', None),
   (u'EQ M(?P<mag>[\d.]+) \[(?P<status>.+)\].*Hora Chilena. (?P<time>\d.+) .UTC..*\((?P<coords>.+,.+)\)', 'UTC', None),
   (u'(?P<status>Auto)EQ (?P<magtype>\w+)(?P<mag>[\d.]+) (?P<time>.+ UTC) \[.* P[SD]T\] .+ mi .+ of (?P<area>.+) depth (?P<depth>\S+) km', 'UTC', None),
   (u'TenemosSismo (?P<source>\S+) (?P<time>\d.+) sensor cercano.*\d+ km al .+ de (?P<area>.+), más información en (?P<link>http\S+)', 'America/Mexico_City', 'Mexico'),
   (u'SASMEX:Sismo del (?P<time>.+): Primera.* Lat:(?P<lat>.+) Long:(?P<lon>.+)', 'America/Mexico_City', None),
   (u'SISMO Magnitud (?P<mag>[\d.]+) Loc. * \S+ km al \S+ de (?P<area>\D+) (?P<time>\d.+) Lat (?P<lat>\S+) Lon (?P<lon>\S+) (Prof|Pf) (?P<depth>\d+)', 'America/Mexico_City', None),
   (u' (?P<time>\d\d:\d\d:\d\d) .+Sismo (?P<status>detectado).*Sensor cercano: (?P<area>\D+)', 'America/Mexico_City', 'Mexico'),
   (u'Aviso.*Sismo (?P<status>detectado) en la region de (?P<area>.+)\..*(?P<link>http\S+)', 'America/Santiago', 'Chile'),
   (u'Sismo en Progreso \(.+\) .+ Detectado por (?P<source>.+) a las: (?P<time>.+) En Estación: (?P<area>.+) Intensidad: (?P<mag>[\d.]+)(?P<magtype>M\w*)', 'America/Santiago', 'Chile'),
   (u'Sismo en proceso en la Region de (?P<area>.+) - (?P<time>.+)CL', 'America/Santiago', 'Chile'),
   (u'Sismo \| Hora Local: (?P<time>.+) \| Lat: (?P<lat>.+) \| Long: (?P<lon>.+) \| Prof .Km.: (?P<depth>.+) \| Mag: (?P<mag>[\d.]+) (?P<magtype>\w+) \| Loc:.+(?P<link>http\S+)', 'America/Santiago', None),
   (u'Sismo en proceso Reporte a las (?P<time>.+) cerca de (?P<area>.+)\.', 'UTC', 'Mexico'),
   (u'Ahora . SSN calculo: (?P<status>.+): M (?P<mag>[\d.]+) Epicentro a . \S+ km al \S+ de (?P<area>\D+) (?P<time>\d.+) Lat (?P<lat>\S+) Lon (?P<lon>\S+) Pf (?P<depth>\d+) km,.*vía (?P<source>\S+)', 'America/Mexico_City', 'Mexico'),
   (u'Ahora (?P<time>\d.+) . - Sismo (?P<status>Detectado): .* km al \S+ de (?P<area>\D+),  📍 vía (?P<source>\S+)', 'America/Mexico_City', 'Mexico'),
   (u'(?P<time>\d.+). Sismo de (?P<mag>[\d.]+) (?P<magtype>M\w*) a (?P<depth>\S+) km de profundidad en (?P<area>.+)', 'America/Bogota', None),
#   (u'Sismografo de la region de (?P<area>.+) registrando sismo en tiempo real.*Sentiste el sismo? Reportalo aqui: (?P<link>http\S+)', 'UTC', 'Chile'),
   (u'Ahora Se registra sismo en la Región de (?P<area>.+). Se inicia monitoreo', 'UTC', 'Chile'),
#   (u'(?P<status>Preliminar) Rev\d.*El sismo que detectamos hace un momento tiene una magnitud posible de (?P<mag>[\d.]+) cerca de las regiones (?P<area>[^;.]+)', 'UTC', 'Chile'),
#   (u'(?P<status>Preliminar) Rev\d.*El sismo que detectamos hace un momento tiene una magnitud posible de (?P<mag>[\d.]+) cerca de (?P<area>[^;.]+)', 'UTC', 'Chile'),
   (u'🔴 Sismo ⚠ (?P<mag>[\d.]+) .(?P<magtype>M\w*). - \S+ km al \S+ de (?P<area>.+)\. UTC: (?P<time>\d.+)\. Detalles en (?P<link>http\S+)', 'UTC', None),
   (u'(?P<status>Prelim) M(?P<mag>[\d.]+) earthquake (?P<area>.+) ...-\d+ (?P<time>\d\d:\d\d UTC)', 'UTC', None),
   (u'Earthquake.*felt (?P<time>.+) in (?P<area>.+)\. Felt it.*See (?P<link>http\S+)', 'UTC', None),
   (u'earthquake M(?P<mag>[\d.]+) strikes (?P<area>.+) (?P<time>\d.+ ago)\.', 'UTC', None),
   (u'earthquake .* M(?P<mag>[\d.]+) strikes \S+ km \S+ of (?P<area>\D+) (?P<time>\d.+ ago). Please report to: (?P<link>http\S+)', 'UTC', None),
   (u'M(?P<mag>[\d.]+) earthquake .* strikes \S+ km \S+ of (?P<area>\D+) (?P<time>\d.+ ago)\.', 'UTC', None),
   (u'(?P<mag>[\d.]+) earthquake, (?P<area>.+)\. (?P<time>.+) at epicenter \(.*, depth (?P<depth>.+)km', 'UTC', None),
   (u'\[V2地震速報\] .+時.+分.+秒に緊急地震速報.+が発信されました。 地震発生時刻: (?P<time>\d+時\d+分\d+秒) 予測手法: .* 震央:.+.北緯(?P<lat>)[\d.]+ 東経(?P<lon>[\d.]+). マグニチュード: (?P<mag>[\d.]+) 震源の深さ: (?P<depth>[\d.]+)km 予測最大震度: (?P<intensity>.+) 近辺の方はご注意ください。', 'Asia/Tokyo', None),
   (u'【地震情報】 .+ (?P<time>\d+時\d+分)  (?P<area>.+) でM(?P<mag>[\d.]+)の地震。  震源 (?P<coords>.+)  深さ (?P<depth>\S+)km', 'Asia/Tokyo', None),
   (u'緊急地震速報  第(?P<status>\d)報.* ： \d+年\d+月\d+日 (?P<time>\d+時\d+分\d+秒) 頃発生、推定規模は M (?P<mag>[\d.]+) 、深さ約(?P<depth>\d+)km、震源地の緯度/経度は (?P<coords>[\d./]+) .*です。', 'Asia/Tokyo', None),
   (u'\[Hi-net\] 発生時刻：(?P<time>.+) 震源地：(?P<area>.+) 緯度：(?P<lat>.+) 経度：(?P<lon>.+) 深さ：(?P<depth>.+)km マグニチュード：(?P<mag>[\d.]+)', 'Asia/Tokyo', None),
   (u'(?P<time>\d+时\d+分\d+).*秒,在河北唐山市开平区.震中纬度:(?P<lat>.+),震中经度:(?P<lon>.+).发生(?P<mag>[\d.]+)级地震', 'Asia/Tokyo', None),
   (u'\[EEW\] ID：.* SEQ：.* 震源地：(?P<area>.+) 緯度：(?P<lat>.+) 経度：(?P<lon>.+) 震源深さ：(?P<depth>.+)km 発生日時：(?P<time>.+) マグニチュード：(?P<mag>.+) 最大震度：(?P<intensity>\S+)', 'Asia/Tokyo', None),
   (u'\[(JMA|EEW)\]: (?P<time>.+) JST 09 <(?P<date>.+) Magnitude: (?P<mag>[\d.]+) Max. Intensity: (?P<intensity>.+) Epicenter: (?P<area>.+) Depth: (?P<depth>.+) km (?P<link>http\S+)', 'Asia/Tokyo', None),
   (u'(?P<status>速報)LV\d.25日　(?P<time>..時..分).*（(?P<coords>.+)）.+M(?P<mag>[\d.]+).+推定(?P<depth>.+)km', 'Asia/Tokyo', None),
   (u'【M(?P<mag>[\d.]+)】(?P<area>\w+) (?P<depth>[\d.]+)km (?P<time>.+ JST)', 'Asia/Tokyo', None),
   (u'▼発生：\d\d-\d\d (?P<time>.+)頃 ▼震源：(?P<area>.+) （(?P<coords>.+) 付近） ▼深さ：(?P<depth>.+)km程度 ▼規模：M(?P<mag>[\d.]+)程度 ▼最大震度：(?P<intensity>.+)程度以上 ※第(?P<status>\d)報推定値', 'Asia/Tokyo', None),
   (u'地震発生時刻: (?P<time>.+) 震央:(?P<area>.+)\(北緯(?P<lat>.+) 東経(?P<lon>.+)\) マグニチュード: (?P<mag>[\d.]+) 震源の深さ: (?P<depth>[\d.]+)km', 'Asia/Tokyo', 'Japan'),
   (u'Magnitude (?P<mag>[\d.]+) Intensity (?P<intensity>.+) earthquake (?P<time>\d.+) \w\w\w-\d\d JST at (?P<area>.+) \((?P<coords>.+)\) Depth (?P<depth>[\d.]+)km +(?P<link>http\S+)', 'Asia/Tokyo', 'Japan'),
   (u'Se ha producido un terremoto de magnitud (?P<mag>[\d.]+) en (?P<area>.+) en la fecha (?P<time>.+) en la siguiente localización: (?P<coords>\S+)', 'UTC', None),
   (u'Inform.*Fecha y Hora del Evento: (?P<time>.+) .GTM -0.:00. Fecha y Hora del Reporte: (?P<update>.+) .GTM -0.:00. Máxima Intensidad Percibida: .+ Número de Sismo: .+ Magnitud y Epicentro Magnitud .+: (?P<mag>[\d.]+) Epicentro: Latitud: (?P<lat>.+) Longitud: (?P<lon>.+) Referencia Geográfica: (?P<area>.+) Profundidad Focal \(Kms\): (?P<depth>.+) Fuente: (?P<source>.+) Reportes de Intensidad por Localidad', 'America/Santiago', None),
   (u'Fecha y Hora Local: (?P<time>.+) Magnitud: (?P<mag>[\d.]+) Profundidad: (?P<depth>.+)km Latitud: (?P<lat>\S+) Longitud: (?P<lon>\S+)', 'America/Lima', None),
   (u'EVENTO SÍSMICO +(?P<date>.+), HORA LOCAL: +(?P<time>\d.+) +LOCALIZACIÓN: .+ km al \S+ de (?P<area>.+), MAG.?\((?P<magtype>M\w*)\): (?P<mag>[\d.]+), PROF..Km. (?P<depth>\d+)\.', 'America/Lima', None),
   (u'ÚltimoSismo (?P<time>.+) Magnitud: (?P<mag>[\d.]+) (?P<magtype>\w+); Profundidad: (?P<depth>\d+) km Referencia: \S+ km al \S+ de (?P<area>.+) NO GENERA', 'America/Lima', 'Peru'),
   (u'Sismo de .* Intensidad en regiones (?P<area>.+): .* Fecha y Hora del Evento: (?P<time>.+) .GTM -0.:00. Fecha y Hora del Reporte: (?P<update>.+) .GTM -0.:00. Máxima Intensidad Percibida: (?P<intensity>.+) .Mercalli', 'America/Santiago', 'Chile'),
   (u'\[(?P<time>\S+) .+:.+] M(?P<mag>[\d.]+) at "(?P<area>.+)" under (?P<depth>.+)km (?P<coords>.+). Estimated max', 'UTC+9', None),
   (u'terremoto (?P<magtype>\w+):(?P<mag>[\d.]+) (?P<time>.+) Lat=(?P<lat>.+) Lon=(?P<lon>.+) Prof=(?P<depth>\d+)Km Zona=(?P<area>[^.]+)\.', 'UTC', None),
   (u'terremoto (?P<magtype>\w+) (?P<mag>[\d.]+) ore (?P<time>.+) IT del (?P<date>.+) a .* km \S+ (?P<area>.+) Prof=(?P<depth>\d+)Km', 'Europe/Rome', 'Italy'),
   (u'Terremoto (?P<magtype>\w+) (?P<mag>[\d.]+) epicentro .+ km .+ (?P<area>.+) alle .+ \((?P<time>.+) UTC\)', 'UTC', 'Italy'),
   (u'Terremoto (?P<magtype>\w+) (?P<mag>[\d.]+) epicentro (?P<area>.+) alle .+ \((?P<time>.+) UTC\)', 'UTC', None),
   (u'Terremoto  - (?P<magtype>\w+): (?P<mag>[\d.]+) (?P<area>.+) (?P<time>\d\d\d\d-\d\d-\d\d \d\d:\d\d:\d\d) \(UTC\) terremoto-(?P<lat>\S+)-(?P<lon>\S+)', 'UTC', None),
   (u'Earthquake (?P<magtype>\w+)\. (?P<mag>[\d.]+) (?P<time>.+) Gmt.(?P<lat>[\d.]+) (?P<lon>[\d.]+) dpt (?P<depth>.+)km.+Data from (?P<source>.+)\.', 'UTC', None),
   (u'\[(?P<status>STIMA PROVVISORIA)\] terremoto Mag tra (?P<mag>[\d.]+) e (?P<maxmag>[\d.]+), ore (?P<time>.+) IT del (?P<date>.+), prov/zona (?P<area>.+),', 'Europe/Rome', 'Italy'),
   (u'Terremoto +- (?P<magtype>\w+): (?P<mag>[\d.]+) \S+ km \S+ di (?P<area>\D+) (?P<time>\d.+) (UTC)', 'UTC', 'Italy'),
   (u'New Earthquake: (?P<magtype>\w+) (?P<mag>[\d.]+) occured on (?P<time>\d.+) UTC: Lat: (?P<lat>.+) Lon: (?P<lon>.+) Depth .km.: (?P<depth>.+) Date', 'UTC', None),
   (u'New Earthquake. . (?P<mag>[\d.]+) .(?P<magtype>\w+). - (?P<area>\D+). (?P<time>\d.+)\.', 'UTC', None),
   (u'earthquake  (?P<time>.+) (?P<status>.+): \(M(?P<mag>[\d.]+)\) (?P<area>[^+\d]+[a-z.]) (?P<coords>[-+\d. ]+) \(.+\) (?P<link>http\S+)', 'UTC', None),
   (u'earthquake  (?P<time>.+) \(M(?P<mag>[\d.]+)\) (?P<area>[^+\d]+[a-z.]) (?P<coords>[-+\d. ]+) \(.+\) (?P<link>http\S+)', 'UTC', None),
   (u'Aviso de nuevo sismo.* (?P<mag>[\d.]+) .(?P<magtype>M\w*). - \S+ km al \S+ de (?P<area>\D+)\. (?P<time>\d.+)\. Sentiste el sismo? Reportalo aqui: (?P<link>http\S+)', 'America/Santiago', 'Chile'),
   (u'(?P<time>\S+ \S+) ALERTA sismo .*: Activacion de Sensor Sismico .(?P<area>[^)]+).', 'America/Santiago', 'Chile'),
   (u'(?P<time>\S+ \S+) Chile/(?P<area>.+) - Activacion Sensor Sismico', 'America/Santiago', 'Chile'),
#   (u'(?P<status>Preliminar).+El sismo .* tiene una magnitud posible de (?P<mag>[\d.]+) cerca de las regiones (?P<area>[^.]+)'), None, 'Chile'),
   (u'Se ha producido un terremoto de magnitud (?P<mag>[\d.]+) en (?P<area>.+) en la fecha (?P<time>.+) en la siguiente localización: (?P<coords>[\d.,])', 'UTC', 'Spain'),
   (u'terremoto (?P<time>.+UTC) \S\S (?P<area>.+\..+) mag=(?P<mag>[\d.]+) prof=(?P<depth>.+)km cálculo (?P<status>\S+) (?P<link>http\S+)', 'UTC', 'Spain'),
   (u'terremoto (?P<time>.+UTC) (?P<area>.+) mag=(?P<mag>[\d.]+) prof=(?P<depth>.+)km cálculo (?P<status>\S+) (?P<link>http\S+)', 'UTC', None),
   (u'M (?P<mag>[\d.]+), (?P<area>[^:]+): (?P<time>.+) +(?P<lat>\S+) +(?P<lon>\S+) +(?P<depth>\d+) km +(?P<status>A|C|M)', 'UTC', None),
   (u'(?P<time>[^;]+); (?P<coords>[^;]+); (?P<mag>\S+) (?P<magtype>[^;]+); (?P<area>[^;]+).*Depth: (?P<depth>\S+) km', 'UTC', None),
   (u'Earthquake: (?P<time>.+) M(?P<mag>[\d.]+) \[(?P<coords>.+)\] (?P<area>.+) http', 'Asia/Hong_Kong', None),
   (u'Earthquake: (?P<time>.+) M(?P<mag>[\d.]+) \[(?P<coords>.+)\] (?P<area>.+) openstreetmap', 'Asia/Hong_Kong', None),
   (u'Earthquake: (?P<time>.+) M(?P<mag>[\d.]+) \[(?P<coords>.+)\] (?P<area>.+)', 'Asia/Hong_Kong', None),
   (u'Earthquake: (?P<time>\d.+)HKT M(?P<mag>[\d.]+) \[(?P<coords>.+)\]', 'Asia/Hong_Kong', None),
   (u'緊急地震速報.　(?P<update>.+)現在.*発生：(?P<time>.+).震源：(?P<area>.+)　(?P<coords>.+)　(?P<depth>.+)km.規模：M(?P<mag>[\d.]+)　最大', 'Asia/Tokyo', 'Japan'),
   (u'緊急地震速報.　(?P<update>.+)現在  第(?P<status>.)報 発生：(?P<time>.+) 震源：(?P<area>.+)　(?P<coords>\d.+)　(?P<depth>\S+)km 規模：M(?P<mag>[\d.]+)　.*(?P<link>http\S+)', 'Asia/Tokyo', 'Japan'),
   (u'緊急地震速報.(?P<update>.+)現在 第(?P<status>.)報　予報 発生：(?P<time>.+) 震源：(?P<area>.+)　(?P<coords>\d.+)　(?P<depth>\S+)km 規模：M(?P<mag>[\d.]+)', 'Asia/Tokyo', 'Japan'),
   (u'【地震情報】(?P<time>.+)頃、(?P<area>.+) 深さ約(?P<depth>.+)kmでM(?P<mag>[\d.]+).最大(?P<intensity>震度.)の地震がありました。', 'Asia/Tokyo', 'Japan'),
   (u'［気象庁情報］\d+日　(?P<time>.+)頃　(?P<area>.+)（(?P<coords>.+)）にて　最大震度(?P<intensity>.+)（M(?P<mag>[\d.]+)）の地震が発生。　震源の深さは(?P<depth>\S+)km。', 'Asia/Tokyo', None),
   (u'［緊急地震速報］(?P<update>.+)現在 第.報.+発生：(?P<time>.+) 震源：(?P<area>\D+)　(?P<coords>\d\　+)　(?P<depth>\d+)km 規模：M(?P<mag>[\d.]+)　.+確度', 'Asia/Tokyo', 'Japan'),
   (u'Earthquake (?P<status>.+) Report.*At around (?P<time>.+), an earthquake with a magnitude of (?P<mag>[\d.]+) occurred [in|near|offshore] (?P<area>.+) at a depth of (?P<depth>\d+)km. The maximum intensity was (?P<intensity>[0-9+])\.', 'Asia/Tokyo', 'Japan'),
   (u'Earthquake (?P<status>.+) Report.*At around (?P<time>.+), an earthquake occurred [in|near|offshore] (?P<area>.+)\.', 'Asia/Tokyo', 'Japan'),
   (u'Earthquake (?P<status>.+) Report.*At around (?P<time>.+), a magnitude (?P<mag>[\d.]+) earthquake occurred [in|near|offshore] (?P<area>.+). The est. maximum intensity is (?P<intensity>[0-9+])\.', 'Asia/Tokyo', 'Japan'),
   (u'Earthquake of Magnitude: ?(?P<mag>[\d.]+), Occurred on: ?(?P<time>.+) IST, Lat: ?(?P<lat>[\d.NS ]+).*Long: ?(?P<lon>[\d.EW ]+), Depth: ?(?P<depth>.+) Km,', 'Asia/Kolkata', None),
   (u'M (?P<mag>[\d.]+), (?P<area>.+): (?P<time>\S+ \S+) (?P<coords>\S+ \S+) (?P<depth>.+) km (?P<status>A|C)', 'UTC', None),
   (u'EEW\S+ .*(?P<area>.+)で地震　最大震度 (?P<intensity>.+).推定. .詳細. (?P<time>.+)発生　M(?P<mag>[\d.]+) 深さ(?P<depth>.+)km', 'Asia/Tokyo', 'Japan'),
   (u'\[[第最](?P<status>.)報\] (?P<time>\S+) (?P<area>.+) 深さ(?P<depth>.+)km M(?P<mag>[\d.]+) 最大(?P<intensity>震度 .) 地震', 'Asia/Tokyo', 'Japan'),
   (u'(?P<time>\S+) .[第最](?P<status>\d)報. (?P<area>.+) M(?P<mag>[\d.]+) 深さ (?P<depth>.+)km 最大(?P<intensity>震度.)', 'Asia/Tokyo', 'Japan'),
   (u'警報:芮氏規模(?P<mag>[\d.]+)深度(?P<depth>.+)公里.+震央:(?P<coords>[\d.,]+)地震時間:(?P<date>.+年.+月.+日)(?P<time>.+點.+分.+秒).+詳情：(?P<link>https:.+)', 'Asia/Taipei', None),
   (u'(?P<status>Prelim) M(?P<mag>[\d.]+) earthquake (?P<area>.+) .* (?P<time>\S+) UTC, updates (?P<link>.+),', 'UTC', None),
   (u'\[(?P<source>.+)\] M(?P<mag>[\d.]+) ...-.. (?P<time>\S+) UTC, .* (?P<area>[A-Z, ]+), Depth:(?P<depth>.+)km, (?P<link>\S+)', 'UTC', None),
   (u'\* MAGNITUDE +(?P<mag>[\d.]+)\n.*\* ORIGIN TIME +(?P<time>[^\n]+)\n.*\* COORDINATES (?P<coords>.+)\n.*\* DEPTH +(?P<depth>[\d]+) KM.*\* LOCATION +(?P<area>[^\n]+)\n.*?(?P<water>(\n      \S[^\n]+)+)', 'UTC', None),
   (u'\* AN EARTHQUAKE WITH A PRELIMINARY MAGNITUDE OF (?P<mag>[\d.]+) OCCURRED IN (?P<area>.+) AT (?P<time>.+ UTC) ON \S+ (?P<date>[^.]+)\..+\* TSUNAMI WAVES ARE FORECAST .+ FOR THE COASTS OF (?P<water>[^*]+)\. \*', 'UTC', None),
   (u'AN EARTHQUAKE WITH A (?P<status>.+) MAGNITUDE OF (?P<mag>[\d.]+) OCCURRED IN THE (?P<area>.+) REGION AT (?P<time>\d+) UTC ON \S+ (?P<date>\S+ \d+ \d+)\..*TSUNAMI WAVES REACHING \d+ TO \d+ METERS ABOVE THE TIDE LEVEL ARE POSSIBLE FOR SOME COASTS OF (?P<water>[^*]+)\. \*', 'UTC', None),
#   (u'Category: .* meters Bulletin Issue Time: (?P<time>.+) UTC.* Magnitude: (?P<mag>[\d.]+)\((?P<magtype>M\w*)\) Lat/Lon: (?P<lat>[\d.-]+) / (?P<lon>[\d.-]+) Affected Region: (?P<water>.*) Note:', 'UTC', None),
   (u'TSUNAMI WARNING 1: See (?P<link>http\S+) +for alert areas.  M(?P<mag>[\d.]+) \S+ \S+ +(?P<area>.+) (?P<time>\d\S+) (?P<date>.+):', 'UTC', None),
   (u'HAZARDOUS TSUNAMI WAVES ARE FORECAST .* for some coasts of (?P<water>.+) after the (?P<status>\S+) M(?P<mag>[\d.]+) occurred (?P<area>.+) at (?P<time>.+ UTC) on \S+ (?P<date>.+\d)', 'UTC', None),
   (u'Sismo. - +Mag (?P<mag>[\d.]+) - (?P<area>[^-]+) - (?P<time>.+) hs:', 'America/Buenos_Aires', 'Argentina'),
   (u'M (?P<mag>[\d.]+), .+: (?P<time>.+) Local Time', 'America/Puerto_Rico', None),
   (u'Sismo (?P<time>.+) HL Mag(?P<mag>[\d.]+) M.;Pro(?P<depth>.+) Km La(?P<lat>.+) Lo(?P<lon>.+) [\d]+ Km', 'America/Lima', None),
   (u'(?P<mag>[\d.]+), \d+ km .+ de (?P<area>.+): Fecha:(?P<time>.+) \(Hora de México\) .*Lat/Lon: (?P<lat>.+)/(?P<lon>.+) Profundidad: (?P<depth>.+) km', 'America/Mexico_City', None),
   (u'(?P<status>\S+): SISMO Magnitud (?P<mag>[\d.]+) Loc. .* km al \S+ de (?P<area>\D+) (?P<time>\d.+) Lat (?P<lat>.+) Lon (?P<lon>.+) (Prof|Pf) (?P<depth>\d+)', 'America/Mexico_City', 'Mexico'),
   (u'(?P<time>.*) \D+, a [\d.]+km .*, prof: (?P<depth>.*)km (?P<source>[^ ]*): M(?P<mag>[\d.]+)', 'America/Lima', None),
   (u'TEMBLOR de (?P<mag>[\d.]+), hoy (?P<time>.+), Epicentro: .+ km .+ de (?P<area>.+), Profundidad (?P<depth>.+) km', 'America/Santiago', 'Chile'),
   (u'SISMO EN CHILE Magnitud de (?P<mag>[\d.]+) (?P<magtype>M\w*), hoy (?P<time>.+), Epicentro: \S+ km al \S+ de (?P<area>.+), Profundidad (?P<depth>.+) km', 'America/Santiago', 'Chile'),
   (u'(?P<status>PRELIMINAR|REVISADO) .*\| Sismo de magnitud (?P<mag>[\d.]+) Richter se produjo a las (?P<time>.+) horas .* a \S+ km al \S+ de (?P<area>.+), región .*, con una profundidad de (?P<depth>[\d.]+) kilómetros', 'America/Santiago', 'Chile'),
   (u'(?P<status>PRELIMINAR|REVISADO) .*\| El sismo se produjo a las (?P<time>.+) horas.*, tuvo una magnitud de (?P<mag>[\d.]+) Richter con epicentro a \S+ km al \S+ de (?P<area>.+), región de .* con una profundidad de (?P<depth>[\d.]+) kilómetros', 'America/Santiago', 'Chile'),
   (u'Hora Local: (?P<time>.+) mag: (?P<mag>[\d.]+), Lat: (?P<lat>.+), Lon: (?P<lon>.+), Prof: (?P<depth>.+), Loc: .+ km .+ de (?P<area>.+)', 'America/Santiago', None),
   (u'\[(?P<time>.+) - .*] Sismo a \S+ km al \S+ de (?P<area>.+), magnitud: (?P<mag>[\d.]+), profundidad: (?P<depth>.+)KM', 'America/Santiago', 'Chile'),
   (u'Sismo de magnitud (?P<mag>[\d.]+) en .*\. A \S+ km al \S+ de (?P<area>.+) +\[\S+ \d+, \d+ (?P<time>\d.+)\]', 'America/El_Salvador', 'El Salvador'),
   (u'Magnitudo: (?P<mag>[\d.]+) SR,.*Waktu gempa: (?P<time>.+) WIB, Lintang: (?P<lat>.+), Bujur: (?P<lon>.+), Kedalaman: (?P<depth>.+) [Kk]m', 'Asia/Jakarta', None),
   (u'Sismo detectado: Intensidad (?P<intensity>.+)\. Sensor ubicado en (?P<area>.+) ../.../.. +(?P<time>..:..:..)', 'America/Mexico_City', 'Mexico'),
   (u'[🔔🚨] - Sismo Detectado - Posible zona epicentral +cerca de (?P<area>.+) 📌', 'America/Mexico_City', 'Mexico'),
   (u'[🔔🚨] - Sismo .* en trayecto - +cerca de (?P<area>.+) 📌', 'America/Mexico_City', 'Mexico'),
   (u'[🔔🚨] - Actividad Sísmica .* - +cerca de (?P<area>.+) 📌', 'America/Mexico_City', 'Mexico'),
   (u'(?P<time>.+) UTC +- +Magnitude.(?P<magtype>M.). (?P<mag>[\d.]+) +- +.* km [^ ]+ (?P<area>.+): +A magnitude', 'UTC', None),
   (u'(?P<time>.+) UTC +- +Magnitude.(?P<magtype>M.). (?P<mag>[\d.]+) +- (?P<area>.+): +A magnitude', 'UTC', None),
   (u'Date: (?P<date>.+) Time: (?P<time>.+) (am|pm) .Thailand. Magnitude: (?P<mag>[\d.]+) richter .*Latitude: (?P<lat>.+) Longt?itude: (?P<lon>.+) Depth: (?P<depth>.+) km', 'Asia/Bangkok', None),
   (u'Mag (?P<mag>[\d.]+) earthquake \S+km \S+ of (?P<area>.+) Time (?P<time>.+) Depth (?P<depth>\S+)km Position (?P<lon>.+[EW]) (?P<lat>.+[NS]) Map', 'UTC', None),
   (u'S-a detectat un nou cutremur in .* judetul (?P<area>.+), la ora (?P<time>.+), cu magnitudinea de (?P<mag>[\d.]+) pe scara Richter', 'Europe/Bucharest', 'Romania'),
   (u'Cutremur .*, judetul (?P<area>\D+) (?P<time>\d.+), mag (?P<mag>[\d.]+)', 'Europe/Bucharest', 'Romania'),
   (u'ird........ (?P<area>.+) (?P<magtype>[Mm]\S+) (?P<mag>[\d.]+) (?P<time>.+) - Event.*see (?P<link>http\S+)', 'UTC', None),
   (u'QUAKE! Magnitude (?P<mag>[\d.]+), \S+km \w+ of (?P<area>.+) on (?P<date>.+) at (?P<time>.+) ET. (?P<link>http\S+)', 'America/New_York', None),
   (u'Mag: (?P<mag>[\d.]+) (?P<date>.+) a las (?P<time>.+) en (?P<area>.+)....a (?P<depth>[\d.]+) km profundidad.*Info: (?P<link>\S+)', 'UTC', None),
   (u'QUAKE: Mag (?P<mag>[\d.]+), ..., (?P<time>.+), .* km \S+ of (?P<area>.+)\. Depth: (?P<depth>[\d.]+) km', "Pacific/Auckland", "New Zealand"),
   (u'Mag: (?P<mag>[\d.]+) - Depth: (?P<depth>[\d.]+) km - UTC (?P<time>.+) - (?P<area>.+) - (?P<source>\S+) Info:', 'UTC', None),
   (u'Mag: (?P<mag>[\d.]+), \S+ km \S+ \S+ (?P<area>.+), (?P<time>\d.+) (?P<link>http\S+)', 'America/Port_of_Spain', None),
   (u'Sismo:(?P<time>.+) .HLV., Mag. (?P<mag>[\d.]+) (?P<magtype>[Mm]\S+), a .* Km al \S+ de (?P<area>.+) (?P<coords>.+), prof. (?P<depth>[\d,.]+) km', 'America/Caracas', "Venezuela"),
   (u'Sismo (?P<time>.+) · Profundidad (?P<depth>[\d.]+) km Magnitud: (?P<mag>[\d.]+) \S+ Km al \S+ de (?P<area>.+)', 'America/Caracas', "Venezuela"),
   (u'[Ss]ismocr (?P<status>\S+), (?P<time>.+), Mag: (?P<mag>[\d,.]+), .* km al \S+ de (?P<area>.+)', 'America/Costa_Rica', 'Costa Rica'),
   (u'[Ss]ismocr (?P<status>\S+), (?P<time>.+), Mag: (?P<mag>[\d,.]+), Prof: (?P<depth>[\d]+) km, .* km al \S+ de (?P<area>.+)', 'America/Costa_Rica', 'Costa Rica'),
   (u'[Ss]ismocr Mag: (?P<mag>[\d,.]+), .* km \S+ de (?P<area>\D+), (?P<time>\d.+) (?P<link>http\S+)', 'America/Costa_Rica', 'Costa Rica'),
   (u'Mag: (?P<mag>[\d.]+), \S+ km .+ de (?P<area>.+), (?P<time>\d.+) (?P<link>http\S+)', 'America/Costa_Rica', None),
   (u'sismo: M (?P<mag>[\d,.]+) - .*km \S+ of (?P<area>\D+) (?P<time>\d.+)', 'UTC', None),
   (u'Fecha: (?P<date>.+). Hora Local: (?P<time>.+). Localización: .* km al \S+ de (?P<area>.+). Coordenadas: (?P<lat>.+) y (?P<lon>.+). Profundidad: (?P<depth>.+) km. Magnitud: (?P<mag>[\d,.]+) (?P<magtype>M\w*)', 'America/Costa_Rica', 'Costa Rica'),
   (u'(?P<mag>[\d.]+) earthquake (close to|occurred near) (?P<area>.+) at (?P<time>.+) UTC!.*(?P<link>http\S+)', 'UTC', None),
   (u'(?P<mag>[\d.]+) earthquake occurred .*km \S+ of (?P<area>.+) at (?P<time>.+) UTC!', 'UTC', None),
   (u'\[(?P<source>.+)\] M(?P<mag>[\d.]+) ...-.. (?P<time>.+) UTC, (?P<area>.+), Depth:(?P<depth>[\d.]+)km, (?P<link>http\S+)', 'UTC', None),
   (u'Reportamos Evento Sísmico - Boletín Actualizado ., (?P<time>.+) hora local. Magnitud (?P<mag>[\d.]+), profundidad (?P<depth>[\d.]+) km, (?P<area>.+) Noticia', 'America/Bogota', 'Colombia'),
   (u'Reportamos Evento Sísmico - Boletín Actualizado ., (?P<time>.+) hora local. Magnitud (?P<mag>[\d.]+), profundidad superficial, (?P<area>.+) Noticia', 'America/Bogota', 'Colombia'),
   (u'(?P<area>\S+) .震中緯經度: (?P<coords>\S+)27.36,88.58 . 发生 3(?P<mag>[\d.]+) 级地震 深度: (?P<depth>[\d.]+)km, 发生时间: (?P<time>.+) (?P<link>http\S+)', 'Asia/Shanghai', None),
   (u'Sismo M (?P<mag>[\d.]+) \S+km \w+ of (?P<area>.+)\. (?P<time>\d.+ UTC) (?P<link>http\S+)', 'UTC', None),
   (u'Sismo M (?P<mag>[\d.]+) \S+ km al \w+ de (?P<area>.+) (?P<time>\d.+ UTC) (?P<link>http\S+) .*Mexico', 'UTC', None),
#   (u'Sismo M (?P<mag>[\d.]+) (?P<area>.+)\. (?P<time>\d.+ UTC) (?P<link>http\S+)', 'UTC', None),   gets a lot of (0, 0) coordinates
   (u'SISMO ID: \S+ (?P<status>\S+) (?P<time>\d.+) TL Magnitud: ?(?P<mag>[\d.]+) Profundidad: ?(?P<depth>[\d.]+) km, a .*Latitud: ?(?P<lat>.+) Longitud: ?(?P<lon>.+) Sintió este sismo', 'America/Guayaquil', None),
   (u'Se registra Sismo en (?P<area>.+) +M (?P<mag>[\d.]+) - Pf (?P<depth>[\d.]+) km.+Hora (?P<time>.+) \(UTC\) Ubicación (?P<coords>.+[WE])', 'UTC', None),
   (u'SismoDetectado. Posible epicentro en: (?P<area>.+)\. (?P<time>.+) +Más información en SASSLA app.', 'America/Mexico_City', 'Mexico'),
   (u'\[국외지진정보\] ?..-.. (?P<time>\S+) (?P<area>.+) \S+ \d+km .* 규모 ?(?P<mag>[\d.]+) (?P<link>http\S+)', 'Asia/Seoul', None),
   (u'\[지진정보\] ?..-.. (?P<time>\S+) (?P<area>.+) \S+ \d+km .* 규모 ?(?P<mag>[\d.]+) (?P<link>http\S+)', 'Asia/Seoul', 'South Korea'),
   (u'แผ่นดินไหว(ขนาด)? .*\((?P<coords>.+)\) ขนาด (?P<mag>[\d.]+) .* เวลา (?P<time>.+) น. .+ \[(?P<source>.+)\]', 'Asia/Bangkok', None),
   (u'A (?P<mag>[\d.]+)-magnitude earthquake jolted .*, at (?P<time>\d.+) .*, according to the (?P<source>.+).The epicenter, with a depth of (?P<depth>[\d.]+) km, was monitored at (?P<lat>.+) latitude and (?P<lon>.+) longitude.', 'Asia/Beijing', None),
   (u'(?P<time>\S+) earthquake with a magnitude of about (?P<mag>[\d.]+) near (?P<area>.+)\. .*\. \S+ damage likely. (?P<link>http\S+)', 'Europe/Zurich', 'Switzerland'),
   (u'Gempa Mag[: ](?P<mag>[\d.]+)( SR)?, (?P<time>\d.+), Lok:(?P<lat>.+),(?P<lon>.+) \(.*, Kedlmn:(?P<depth>[\d.]+) Km', 'Asia/Jakarta', None),
   (u'Peringatan Dini Tsunami di (?P<water>.+), Gempa Mag:(?P<mag>[\d.]+), (?P<time>.+), Lok:(?P<lat>\S+)LS,(?P<lon>\S+)BT,Kdlmn:(?P<depth>[\d.]+)Km', 'Asia/Jakarta', None),
   (u'Date and Time: (?P<time>.+) Magnitude = (?P<mag>[\d.]+) Depth = (?P<depth>[\d.]+) kilometers? Location = (?P<coords>.+[EW]) -', 'Asia/Manila', None),
   (u'Region: ?(?P<area>.+) Mag: ?(?P<mag>[\d.]+) UTC: ?(?P<time>.+) Lat: ?(?P<lat>\S+) Lon: ?(?P<lon>\S+) Dep: ?(?P<depth>[\d.]+)km (?P<link>http\S+)', 'UTC', None),
   (u'Earthquake +Magnitude (?P<mag>[\d.]+) reported \S+km \S+ of (?P<area>.+) at (?P<time>\d.+ UTC) (?P<link>http\S+)', 'UTC', None),
   (u'Earthquake: +(?P<magtype>M\w*) (?P<mag>[\d.]+) (?P<area>.+): .* Date time +(?P<time>\d.+)\.\d UTC Location +(?P<coords>.+) Depth +(?P<depth>[\d.]+) km +(?P<link>http\S+)', 'UTC', None),
   (u'Information Bulletin Issue Time: (?P<time>\d.+) UTC Preliminary Magnitude: (?P<mag>[\d.]+)\((?P<magtype>M\w*)\) Lat/Lon: (?P<lat>\S+) / (?P<lon>\S+) Affected Region: (?P<area>.+) Note:', 'UTC', None),
#   (u'Magnitude +(?P<magtype>M\w*) (?P<mag>[\d.]+) Region +(?P<area>.+) Date time +(?P<time>\d.+)\.\d UTC Location +(?P<coords>.+) Depth +(?P<depth>[\d.]+) km (?<link>http\S+)', 'UTC', None),
   (u'(?P<magtype>M\w*) (?P<mag>[\d.]+) \(.+ ago\) \d+km (?P<coords>.+°[NS].+°[EW]) (?P<time>.+ UTC)', 'UTC', None),
   (u'(?P<magtype>M\w*)=(?P<mag>[\d.]+), (?P<area>.+) .Depth: (?P<depth>\S+) km., (?P<time>.+) - Full details here: (?P<link>http\S+)', 'UTC', None),
   (u'(?P<area>.+), (?P<magtype>M\S+=) ?(?P<mag>[\d.]+), (?P<time>.* UTC)', 'UTC', None),
   (u'(?P<mag>[\d.]+), (?P<area>.+): (?P<time>\S+ \S+) (?P<coords>\S+ \S+) (?P<depth>[\d.]+) km (?P<status>automatic|manual)', 'UTC', None),
   (u'(?P<mag>[\d.]+) (?P<magtype>\w+), .* Km .* from (?P<area>.+): (?P<time>.+) (?P<status>automatic|revised)', 'UTC', 'Greece'),
   (u'(?P<magtype>\w+) +(?P<mag>[\d.]+).* +(?P<area>.+):.*[Tt]ime +(?P<time>.+ (UTC)?) .*Location +(?P<coords>.+) +Depth +(?P<depth>[\d.]+) +km', 'UTC', None),
   (u'(?P<status>\w+) detection of seismic event: magnitude (?P<mag>[\d.]+) - (?P<time>.+) - (?P<area>.+) region', 'UTC', 'Canada'),
   (u'(?P<time>.+) JST .* of (?P<area>.+) Depth: (?P<depth>.+)km Mag.: (?P<mag>[\d.]+) JMA Scale:', 'Asia/Tokyo', 'Japan'),
   (u'(?P<time>\d.+)\.\d\d (?P<lat>\d.+[NS]) (?P<lon>\d.+[EW]) (?P<depth>[\d.]+)km M(?P<mag>[\d.]+)', 'Asia/Tokyo', None),
   (u'(?P<time>\d.+)\.\d\d .* (?P<lat>\d.+[NS]) (?P<lon>\d.+[EW]) (?P<depth>[\d.]+)km M(?P<mag>[\d.]+)', 'Asia/Tokyo', None),
   (u'Origin date/time: (?P<time>.+) ; Location: (?P<area>.+) ; Lat/long: (?P<coords>.+) ; Depth: (?P<depth>.+) km ; Magnitude: +(?P<mag>[\d.]+)', 'Europe/London', None),
   (u'(?P<time>.+[\d]) [A-Z|].*, a .*km de (?P<area>.+), prof: (?P<depth>.+)km (?P<source>.+): .*M(?P<mag>[\d.]+) .(?P<status>Preliminar|Revisión)', 'America/Santiago', 'Chile'),
   (u'(?P<magtype>M\w*) (?P<mag>[\d.]+) .* (?P<depth>\d+)km (?P<coords>.+[NS].+[EW]) (?P<time>\d.+) \+03', 'Asia/Istanbul', None),
   (u'(?P<magtype>M\w*) (?P<mag>[\d.]+) (?P<area>.+): (?P<time>\d.+) UTC Lat: (?P<lat>.+) - Long: (?P<lon>.+) - Depth: (?P<depth>.+) - Mag: .+ (?P<link>http\S+)', 'UTC', None),
   (u'(?P<magtype>M\w*) (?P<mag>[\d.]+) earthquake \((?P<status>.+)\) occured at (?P<time>.+) UTC, .+km .+ of (?P<area>.+) (?P<link>http\S+)', 'UTC', None),
   (u'(?P<area>.+) Büyüklük: (?P<mag>[\d.]+) Tarih: (?P<date>.+) Saat: (?P<time>.+) Derinlik:  ?(?P<depth>\d+) km', 'Asia/Istanbul', 'Turkey'),
   (u'(?P<alert>\S+) earthquake alert .Magnitude (?P<mag>[\d.]+)(?P<magtype>\w+), Depth:(?P<depth>.+)km. in (?P<area>\D+) (?P<time>\d.+) UTC', 'UTC', None), # GDACS RSS
   (u'(?P<alert>\S+) earthquake alert .(?P<mag>[\d.]+)(?P<magtype>\w+),depth:(?P<depth>.+)km. in (?P<area>\D+) (?P<time>\d.+) UTC', 'UTC', None), # GDACS Twitter
   (u'(?P<status>Preliminary) M(?P<mag>[\d.]+) earthquake \S+ from (?P<area>\D+) in \S+, (?P<date>.+) UTC by @?raspishake', 'UTC', None),
   (u'\d+\w\w\w/(?P<time>[^;]+); Sismo (?P<magtype>M\w*) (?P<mag>[\d.]+) (?P<area>.+), epicentro a (?P<coords>.+) y profundidad de (?P<depth>\d+)km, registrado a .+km del RaspberryShake (?P<source>\S+)', 'America/Panama', None),
   (u'\d+km \S+ of (?P<area>.+) earthquake Mag (?P<mag>[\d.]+) -.*\((?P<time>.+ GMT)\)', 'UTC', None),
   (u'(?P<source>.+) reports a M(?P<mag>[\d.]+) earthquake .+km .+ of (?P<area>.+) on (?P<date>.+) @ (?P<time>.+) UTC (?P<link>http\S+)', 'UTC', 'US'),
   (u'(?P<time>.+) GMT - Shaking reported near (?P<area>.?)\. (?P<link>http\S+)', 'UTC', None),
   (u'(?P<time>\d\d\d\d-\d\d-\d\dT\d\d:\d\d:\d\d)Z: M(?P<mag>[\d.]+) (?P<area>[^0-9]+)', 'UTC', None),
   (u'(?P<time>\d.+) \(M(?P<mag>[\d.]+)\) (?P<area>.+) (?P<lat>[-+\d.]+) (?P<lon>[-+\d.]+) \(', 'UTC', None),   # we sure this is warranted? gave problems before
]

for index, (expression, timezone, country) in enumerate(patterns):
   try: expression = re.compile(expression, re.IGNORECASE | re.UNICODE | re.DOTALL)
   except: utils.error("Could not compile regular expression %r" % expression)

   patterns[index] = expression, timezone, country
