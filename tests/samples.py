"""Realistic collection records, shaped exactly like label_data.html builds them
(collectionData), with the edge cases a backup format must survive."""
from __future__ import annotations

import copy


def record(**over) -> dict:
    data = {
        "siteName": "Umstead SP — Reedy Creek", "dateStart": "2025-06-14", "dateEnd": "2025-06-14", "isRange": False,
        "timeOfCollection": "21:15 - 22:40", "timeStart": "21:15", "timeEnd": "22:40", "collector": "A. Eargle",
        "specimenId": "ENT-0001", "identification": "Photinus pyralis", "identifier": "O. Mettam", "numSpecimens": "3",
        "baseTemp": 50, "accumStartMD": "03-01", "inputMode": "latlon",
        "location": "Raleigh, Wake County, North Carolina, United States", "city": "Raleigh", "state": "North Carolina",
        "country": "United States", "countryCode": "us", "provider": "ncei",
        "lat": 35.8301, "lon": -78.7639, "elevation": 113,
        "stationName": "RALEIGH DURHAM INTL AP", "stationId": "USW00013722", "stationDist": 4.2,
        "gddStart": 1234.5, "gddEnd": 1234.5, "dailyGddStart": 21.5,
        "highTemp": 88.0, "lowTemp": 67.1, "avgTemp": 77.6, "tempAtTime": 79.3,
        "sunset": "8:31 PM", "humidity": {"atTime": 71, "avg": 64},
        "rainfallMonth": 3.42, "rainfallWeek": 0.85, "maxTemp": 86,
        "userNotes": 'Under oaks, "flash" pattern J-stroke,\nnear creek; 2nd visit', "collectionMethod": "Hand net",
    }
    data.update(over)
    return data


def entry(i: int, **over) -> dict:
    return {"id": f"00000000-0000-4000-8000-{i:012d}", "createdAt": f"2025-06-{14 + i % 10:02d}T22:50:00.000Z",
            "updatedAt": f"2025-06-{14 + i % 10:02d}T23:00:00.000Z", "deleted": False, "data": record(**over)}


def samples() -> list[dict]:
    return copy.deepcopy([
        entry(1),
        entry(2, isRange=True, dateEnd="2025-06-21", gddEnd=1401.0, specimenId="ENT-0002",
              timeStart="", timeEnd="", timeOfCollection="", humidity={"atTime": None, "avg": 58}),
        entry(3, lat=-33.8688, lon=151.2093, inputMode="city", country="Australia", countryCode="au", provider="open-meteo",
              stationName="Open-Meteo Grid Point", stationId="OM:-33.8688,151.2093", stationDist=0,
              lowTemp=-2.5, highTemp=9.0, tempAtTime=-1.0, identification="Coléoptère sp. — ×2 «test»",
              collector="Zoë Müller", userNotes="=SUM(A1:A3) should stay text", specimenId="@first",
              collectionMethod="+light trap", siteName="-dash site"),
        entry(4, elevation=None, tempAtTime=None, sunset="", humidity={"atTime": None, "avg": None},
              rainfallWeek=0, rainfallMonth=0, userNotes="", collectionMethod="", specimenId="",
              legacyFireflyField={"flashes": 7, "note": "kept via Extra Fields"}),
        entry(5, timeStart="09:05", timeEnd="", timeOfCollection="09:05", gddStart=0, gddEnd=0, dailyGddStart=0),
    ])
