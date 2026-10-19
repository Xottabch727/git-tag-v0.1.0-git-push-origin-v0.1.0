import codecs
import json


def car_line(num, steam, first, last, best, total=None, laps=0, model=0):
    return {
        "car": {"raceNumber": num, "carModel": model, "teamName": "",
                "drivers": [{"firstName": first, "lastName": last, "playerId": steam}]},
        "currentDriver": {"firstName": first, "lastName": last, "playerId": steam},
        "timing": {"bestLap": best, "totalTime": total if total is not None else 0, "lapCount": laps},
    }


def session_bytes(lines, session_type="Q"):
    obj = {"sessionType": session_type, "trackName": "monza",
           "sessionResult": {"leaderBoardLines": lines}}
    return codecs.BOM_UTF16_LE + json.dumps(obj).encode("utf-16-le")


def quali_lines():
    return [
        car_line(10, "S10", "Ann", "A", 100000),
        car_line(11, "S11", "Bob", "B", 100200),
        car_line(12, "S12", "Cid", "C", 100400),
        car_line(13, "S13", "Dan", "D", 100600),
        car_line(14, "S14", "Eve", "E", 2147483647),
    ]


def race_lines():
    return [
        car_line(10, "S10", "Ann", "A", 100000, total=3600000, laps=30),
        car_line(11, "S11", "Bob", "B", 100200, total=3605000, laps=30),
        car_line(12, "S12", "Cid", "C", 100400, total=3607000, laps=30),
        car_line(13, "S13", "Dan", "D", 100600, total=3500000, laps=29),
    ]
