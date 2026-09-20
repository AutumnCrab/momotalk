# -*- coding: utf-8 -*-
import datetime
import unittest

from momotalk import persona_loader


class ScheduleLogicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 주간 스케줄만 검증한다. 해마다 달라지는 특별 이벤트 날짜는 이 테스트 범위가 아니다.
        persona_loader.event_loader.activity_for = lambda key, date: None
        persona_loader.event_loader.awake_for = lambda key, date: None

    def test_sleeping_prefect_members_are_not_co_present(self):
        now = datetime.datetime(2026, 9, 20, 2, 9)  # 일요일 새벽
        hina = persona_loader.load_persona("hina")
        ako = persona_loader.load_persona("ako")
        chinatsu = persona_loader.load_persona("chinatsu")

        self.assertTrue(persona_loader.is_awake(hina, now))
        self.assertFalse(persona_loader.is_awake(ako, now))
        self.assertFalse(persona_loader.is_awake(chinatsu, now))

        _, hina_entry = persona_loader.current_activity_entry(hina, now)
        _, ako_entry = persona_loader.current_activity_entry(ako, now)
        _, chinatsu_entry = persona_loader.current_activity_entry(chinatsu, now)
        self.assertEqual("선도부실", persona_loader._entry_place(hina_entry))
        self.assertEqual("집", persona_loader._entry_place(ako_entry))
        self.assertEqual("집", persona_loader._entry_place(chinatsu_entry))

        note = persona_loader.build_co_present_note("hina", now)
        self.assertNotIn("아코", note)
        self.assertNotIn("치나츠", note)

    def test_awake_members_at_same_place_are_co_present(self):
        now = datetime.datetime(2026, 9, 19, 13, 30)  # 토요일 당직 점심
        note = persona_loader.build_co_present_note("hina", now)
        self.assertIn("아코", note)
        self.assertIn("치나츠", note)
        self.assertNotIn("이오리", note.split("[지금 같이 있는 사람]")[-1].split("[지금 따로 있는 사람]")[0])

    def test_structured_busy_tag_controls_availability(self):
        now = datetime.datetime(2026, 9, 19, 21, 30)
        hina = persona_loader.load_persona("hina")
        self.assertEqual("busy", persona_loader.availability_status(hina, now))

    def test_sleeping_game_development_members_are_not_co_present(self):
        now = datetime.datetime(2026, 9, 20, 2, 15)
        note = persona_loader.build_co_present_note("momoi", now)
        for name in ("미도리", "유즈", "아리스", "케이"):
            self.assertNotIn(name, note)

    def test_game_development_club_sleeps_three_nights(self):
        for day in (15, 17, 19):  # 월·수·금 밤을 넘긴 화·목·토 새벽
            now = datetime.datetime(2026, 9, day, 3, 5)
            for key in ("momoi", "midori", "yuzu", "aris"):
                persona = persona_loader.load_persona(key)
                _, entry = persona_loader.current_activity_entry(persona, now)
                self.assertEqual("게임개발부 부실", persona_loader._entry_place(entry))
                self.assertEqual("sleep", persona_loader.availability_status(persona, now))

    def test_hina_sleeps_in_prefect_room_twice(self):
        for day in (16, 19):  # 화·금 밤을 넘긴 수·토 새벽
            now = datetime.datetime(2026, 9, day, 3, 5)
            hina = persona_loader.load_persona("hina")
            _, entry = persona_loader.current_activity_entry(hina, now)
            self.assertEqual("선도부실", persona_loader._entry_place(entry))
            self.assertEqual("sleep", persona_loader.availability_status(hina, now))

    def test_ako_stays_with_hina_on_friday_night(self):
        now = datetime.datetime(2026, 9, 19, 3, 5)
        for key in ("hina", "ako"):
            persona = persona_loader.load_persona(key)
            _, entry = persona_loader.current_activity_entry(persona, now)
            self.assertEqual("선도부실", persona_loader._entry_place(entry))
            self.assertEqual("sleep", persona_loader.availability_status(persona, now))

    def test_hina_has_a_full_rest_day_at_home(self):
        hina = persona_loader.load_persona("hina")
        sunday = hina["activity"]["sun"]
        self.assertTrue(all(entry.get("place") == "집" for entry in sunday.values()))
        self.assertFalse(any(entry.get("tag") == "W" for entry in sunday.values()))


if __name__ == "__main__":
    unittest.main()
