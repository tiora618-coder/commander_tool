import random


class MulliganGame:
    def __init__(self, deck):
        self.deck = deck
        self.games_played = 0
        self.total_mulligans = 0
        self.total_rating = 0
        self.current_mulligans = 0

    def start_new_game(self):
        self.deck.shuffle()
        self.current_mulligans = 0
        return self.deck.draw_7()

    def mulligan(self):
        self.current_mulligans += 1
        self.deck.shuffle()
        return self.deck.draw_7()

    def keep(self, rating: int):
        self.games_played += 1
        self.total_mulligans += self.current_mulligans
        self.total_rating += rating
