"""Unit tests for the Scrum Poker room logic.

Standard library only - run with:  python -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from server import DECK, Room, card_value


class DeckTests(unittest.TestCase):
    def test_deck_is_the_agreed_sequence(self):
        self.assertEqual(
            DECK,
            ["0.25", "0.5", "1", "2", "3", "5", "8", "13", "21+", "coffee"],
        )

    def test_coffee_is_not_counted(self):
        self.assertIsNone(card_value("coffee"))

    def test_21_plus_counts_as_21(self):
        self.assertEqual(card_value("21+"), 21.0)

    def test_plain_numbers_are_parsed(self):
        self.assertEqual(card_value("0.25"), 0.25)
        self.assertEqual(card_value("13"), 13.0)

    def test_unknown_card_has_no_value(self):
        self.assertIsNone(card_value("banana"))
        self.assertIsNone(card_value(None))


class RoomTestCase(unittest.TestCase):
    def setUp(self):
        self.room = Room()
        self.po = self.room.join("Max Mustermann", "product_owner")
        self.dev_a = self.room.join("Alex", "technical_operations")
        self.dev_b = self.room.join("Sam", "technical_operations")

    def participant(self, name):
        return next(
            p for p in self.room.snapshot()["participants"] if p["name"] == name
        )


class JoinTests(RoomTestCase):
    def test_everybody_is_seated(self):
        names = [p["name"] for p in self.room.snapshot()["participants"]]
        self.assertEqual(names, ["Max Mustermann", "Alex", "Sam"])

    def test_unknown_role_falls_back_to_estimator(self):
        token = self.room.join("Guest", "chief_of_everything")
        self.assertFalse(self.room.is_product_owner(token))

    def test_empty_name_becomes_anonymous(self):
        self.room.join("   ", "technical_operations")
        self.assertEqual(self.participant("Anonymous")["name"], "Anonymous")

    def test_long_names_are_truncated(self):
        self.room.join("x" * 100, "technical_operations")
        longest = max(
            len(p["name"]) for p in self.room.snapshot()["participants"]
        )
        self.assertLessEqual(longest, 24)


class VotingTests(RoomTestCase):
    def test_vote_is_recorded_but_hidden(self):
        self.room.vote(self.dev_a, "5")
        alex = self.participant("Alex")
        self.assertTrue(alex["hasVoted"])
        self.assertIsNone(alex["vote"], "votes must stay secret before reveal")

    def test_voting_the_same_card_again_takes_it_back(self):
        self.room.vote(self.dev_a, "5")
        self.room.vote(self.dev_a, "5")
        self.assertFalse(self.participant("Alex")["hasVoted"])

    def test_cards_outside_the_deck_are_rejected(self):
        self.assertFalse(self.room.vote(self.dev_a, "34"))
        self.assertFalse(self.participant("Alex")["hasVoted"])

    def test_no_voting_after_reveal(self):
        self.room.reveal(self.po)
        self.assertFalse(self.room.vote(self.dev_a, "5"))

    def test_voted_count(self):
        self.room.vote(self.dev_a, "5")
        self.assertEqual(self.room.snapshot()["votedCount"], 1)


class PermissionTests(RoomTestCase):
    def test_only_product_owner_may_reveal(self):
        self.assertFalse(self.room.reveal(self.dev_a))
        self.assertFalse(self.room.snapshot()["revealed"])
        self.assertTrue(self.room.reveal(self.po))
        self.assertTrue(self.room.snapshot()["revealed"])

    def test_only_product_owner_may_reset(self):
        self.assertFalse(self.room.reset(self.dev_a))
        self.assertTrue(self.room.reset(self.po))

    def test_only_product_owner_may_remove_somebody(self):
        alex_id = self.participant("Alex")["id"]
        self.assertFalse(self.room.remove_participant(self.dev_b, alex_id))
        self.assertTrue(self.room.remove_participant(self.po, alex_id))
        names = [p["name"] for p in self.room.snapshot()["participants"]]
        self.assertNotIn("Alex", names)

    def test_product_owner_cannot_remove_themselves(self):
        po_id = self.participant("Max Mustermann")["id"]
        self.assertFalse(self.room.remove_participant(self.po, po_id))

    def test_unknown_session_cannot_do_anything(self):
        self.assertFalse(self.room.vote("bogus-token", "5"))
        self.assertFalse(self.room.reveal("bogus-token"))
        self.assertFalse(self.room.touch("bogus-token"))


class RevealTests(RoomTestCase):
    def test_votes_become_visible(self):
        self.room.vote(self.dev_a, "3")
        self.room.reveal(self.po)
        self.assertEqual(self.participant("Alex")["vote"], "3")

    def test_statistics_ignore_coffee(self):
        self.room.vote(self.dev_a, "0.25")
        self.room.vote(self.dev_b, "21+")
        self.room.vote(self.po, "coffee")
        self.room.reveal(self.po)
        stats = self.room.snapshot()["stats"]
        self.assertAlmostEqual(stats["average"], 10.62)
        self.assertEqual(stats["min"], "0.25")
        self.assertEqual(stats["max"], "21+")
        self.assertFalse(stats["consensus"])

    def test_consensus_is_detected(self):
        self.room.vote(self.dev_a, "8")
        self.room.vote(self.dev_b, "8")
        self.room.reveal(self.po)
        stats = self.room.snapshot()["stats"]
        self.assertTrue(stats["consensus"])
        self.assertEqual(stats["average"], 8)

    def test_no_statistics_when_everybody_skips(self):
        self.room.vote(self.dev_a, "coffee")
        self.room.vote(self.dev_b, "coffee")
        self.room.reveal(self.po)
        self.assertIsNone(self.room.snapshot()["stats"])

    def test_no_statistics_before_reveal(self):
        self.room.vote(self.dev_a, "5")
        self.assertIsNone(self.room.snapshot()["stats"])


class ResetTests(RoomTestCase):
    def test_reset_starts_a_clean_round(self):
        self.room.vote(self.dev_a, "5")
        self.room.reveal(self.po)
        before = self.room.snapshot()["round"]

        self.room.reset(self.po)
        state = self.room.snapshot()

        self.assertEqual(state["round"], before + 1)
        self.assertFalse(state["revealed"])
        self.assertEqual(state["votedCount"], 0)
        self.assertIsNone(state["stats"])


class PersonalStateTests(RoomTestCase):
    def test_you_see_your_own_vote_before_reveal(self):
        self.room.vote(self.dev_a, "5")
        you = self.room.personal_state(self.dev_a)["you"]
        self.assertEqual(you["vote"], "5")
        self.assertEqual(you["name"], "Alex")

    def test_you_cannot_see_other_votes_before_reveal(self):
        self.room.vote(self.dev_b, "13")
        state = self.room.personal_state(self.dev_a)
        sam = next(p for p in state["participants"] if p["name"] == "Sam")
        self.assertTrue(sam["hasVoted"])
        self.assertIsNone(sam["vote"])

    def test_unknown_token_has_no_seat(self):
        self.assertIsNone(self.room.personal_state("bogus-token")["you"])

    def test_leaving_frees_the_seat(self):
        self.room.leave(self.dev_a)
        names = [p["name"] for p in self.room.snapshot()["participants"]]
        self.assertNotIn("Alex", names)


if __name__ == "__main__":
    unittest.main()
