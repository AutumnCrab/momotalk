# -*- coding: utf-8 -*-
"""
요일/시간 스케줄러.

별도 스레드 대신 QTimer 로 15초마다 현재 시각을 확인합니다.
(UI 와 같은 스레드에서 동작하므로 초보자가 다루기 안전합니다.)

정해진 요일+시각(분 단위)이 되면 message_ready 신호로
(캐릭터 key, 메시지 리스트) 를 내보냅니다.
같은 일정은 하루에 한 번만 발생하도록 처리합니다.

주의: 프로그램이 켜져 있는 동안에만 메시지가 도착합니다.
      (예: 07:00 일정인데 07:05 에 켜면 그날 07:00 건은 지나갑니다.)
"""

from datetime import datetime

from PyQt5.QtCore import QObject, QTimer, pyqtSignal


class Scheduler(QObject):
    message_ready = pyqtSignal(str, list)   # (char_key, messages)

    CHECK_INTERVAL_MS = 15 * 1000

    def __init__(self, characters):
        super().__init__()
        self.characters = characters
        self._fired = set()     # "char|time|YYYY-MM-DD" 형태로 중복 발사 방지
        self.timer = QTimer(self)
        self.timer.setInterval(self.CHECK_INTERVAL_MS)
        self.timer.timeout.connect(self._tick)

    def start(self):
        self.timer.start()
        self._tick()   # 켜자마자 한 번 확인

    def _tick(self):
        now = datetime.now()
        weekday = now.weekday()
        hhmm = now.strftime("%H:%M")
        today = now.strftime("%Y-%m-%d")

        # 어제 이전에 발사된 기록은 정리
        self._fired = {k for k in self._fired if k.endswith(today)}

        for char in self.characters:
            for entry in char.get("schedule", []):
                if weekday in entry["days"] and entry["time"] == hhmm:
                    key = "%s|%s|%s" % (char["key"], entry["time"], today)
                    if key not in self._fired:
                        self._fired.add(key)
                        self.message_ready.emit(char["key"], list(entry["messages"]))
