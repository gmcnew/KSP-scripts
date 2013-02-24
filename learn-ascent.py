import argparse
import math
import os
import random
import sys

import ascent
import planet

class Profile:

    # Class variables.
    planet = None
    alt0   = None
    alt1   = None
    accel  = None
    drag   = None

    def __init__(self, gt0, gt1, curve):
        self.gt0    = sorted([0,   gt0, self.alt1])[1]
        self.gt1    = sorted([0,   gt1, self.alt1])[1]
        self.curve  = sorted([0, curve,   2])[1]
        self._calc_score()
        self.generation = 1

    @classmethod
    def init(cls, planet, alt0, alt1, accel, drag):
        cls.planet = planet
        cls.alt0   = alt0
        cls.alt1   = alt1
        cls.accel  = accel
        cls.drag   = drag

    @classmethod
    def from_string(cls, str):
        tokens = [float(f) for f in str.strip().split(" ")]
        if len(tokens) == 4:
            tokens.append(-1)
        (gt0, gt1, curve, score) = tokens[:4]
        return Profile(gt0, gt1, curve)

    #9.72 23.87 0.3381 1119.067026
    @classmethod
    def random(cls):
        gt0 = random.random() * (cls.alt1 / 2)
        gt1 = gt0 + random.random() * (cls.alt1 - gt0)
        curve = random.random() * 2
        return Profile(gt0, gt1, curve)

    def mutated(self):
        return Profile( self._mutate(self.gt0),
                        self._mutate(self.gt1),
                        self._mutate(self.curve))

    def _mutate(self, value):
        amount = 0.01

        # Mutate more slowly in later generations.
        #amount /= math.log(self.generation + 1)

        return value + (random.random() - 0.5) * math.sqrt(value) * amount

    def _calc_score(self):
        try:
            self.ascent = ascent.climbSlope(self.planet,
                    orbitAltitude       = self.alt1 * 1000,
                    gravityTurnStart    = self.gt0 * 1000,
                    gravityTurnEnd      = self.gt1 * 1000,
                    gravityTurnCurve    = self.curve,
                    acceleration        = self.planet.gravity() * self.accel,
                    initialAltitude     = self.alt0 * 1000,
                    dragCoefficient     = self.drag
                    )
            self.score = self.ascent.deltaV()
        except ascent.BadFlightPlanException as bfpe:
            self.score = -1
            self.ascent = None

    def _combine(self, a, b):
        average = (a ** 2 + b ** 2) ** 0.5
        return self._mutate(average)

    def __lt__(self, other):
        return self.score != -1 and self.score < other.score

    def combine(self, other):
        return Profile(self._combine(self.gt0,   other.gt0),
                       self._combine(self.gt1,   other.gt1),
                       self._combine(self.curve, other.curve))

    def better_than(self, other):
        return (not other) or other.score < 0 or (self.score > 0 and self.score < other.score)

    def worse_than(self, other):
        return (not other) or self.score > other.score

    def __str__(self):
        return "%f %f %f %f" % (self.gt0, self.gt1, self.curve, self.score)

    def guide(self):
        angleStep = 15
        guide = "(angle alt) "
        for angle in range(0, 90 + 1, angleStep):
            dy = self.gt1 - self.gt0
            alt = self.gt0 + ((float(angle) / 90) ** (1.0 / self.curve)) * dy
            if angle != 0:
                guide += ", "
            guide += "%d %4.1f" % (angle, alt)
        guide += "\n"
        if self.ascent:
            guide += "average atmospheric pressure: %f\n" % (self.ascent.avgAtm)
            guide += "dv to circularize at apoapsis: %f\n" % (self.ascent.dV_circ)
            #guide += str(self.ascent) + "\n"
        return guide

def select(pool, s):
    for profile in pool:
        if random.random() > s:
            return profile
    return pool[-1]


def learnAscent(planetName, startAlt = 0, endAlt = None, accel = 2, drag = 0.2, poolSize = 20, fileIn = None):

    p = planet.planets[planetName.lower()]

    if endAlt is None:
        endAlt = math.ceil(p.topOfAtmosphere() / 5000) * 5

    print("ascending to %d km with %.2f g's of acceleration" % (endAlt, accel))
    Profile.init(p, startAlt, endAlt, accel, drag)

    fileOut = "%s_%d_%d_%.2f_%.2f.txt" % (p.name, startAlt, endAlt, accel, drag)

    if fileIn is None:
        fileIn = fileOut

    pool = []

    if fileIn and os.path.exists(fileIn):
        with open(fileIn) as f:
            for line in f.readlines():
                pool.append(Profile.from_string(line))

    while len(pool) < poolSize:
        profile = Profile.random()
        pool.append(profile)

    bestEver = None
    gen = 1
    needNewline = False

    try:
        while True:
            best = None
            worst = None
            total = 0
            successes = 0
            # 7.6 45.0 0.653 = 4435.43
            # 8.7 45.9 0.610 = 4436.00
            candidates = []
            for profile in pool:
                profile.generation = gen
                if profile.better_than(best):
                    best = profile
                    if profile.better_than(bestEver):
                        bestEver = profile
                        if (needNewline):
                            sys.stdout.write("\n")
                            needNewline = False
                        print(" " * 8 + str(profile))
                        print(profile.guide())

                if profile.worse_than(worst):
                    worst = profile

                if profile.score > 0:
                    total += profile.score
                    successes += 1
                    candidates.append(profile)
            candidates.sort()
            if successes:
                needNewline = True
                sys.stdout.write("\r%6d: best %f, average %f" % (gen, best.score, total / successes))
            newPool = []
            SELECT_P = 0.5

            # Automatically select the top candidate and a mutant of it.
            if candidates:
                newPool.append(candidates[0])
                newPool.append(candidates[0].mutated())

            while len(newPool) < min(poolSize / 2, successes):
                a = select(candidates, SELECT_P)
                b = select(candidates, SELECT_P)
                newPool.append(a.combine(b))

            while len(newPool) < poolSize:
                newPool.append(Profile.random())
            pool = newPool
            gen += 1

    except KeyboardInterrupt:
        pool.sort()
        with open(fileOut, "w") as f:
            for profile in pool:
                f.write("%s\n" % profile)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description = "Learn an ascent.")
    parser.add_argument('planet', metavar='planet',
                       help='planet or moon')
    parser.add_argument('alt0', metavar='alt0', type=int,
                       help='initial altitude (km; defaults to 0)')
    parser.add_argument('alt1', metavar='alt1', type=int,
                       help='final altitude (km; defaults to the nearest 5 km mark above the atmosphere)')
    parser.add_argument('-a', metavar='accel', type=float, default=2,
                       help='ship acceleration as a multiple of planet surface gravity (default: %(default)s)')
    parser.add_argument('-d', metavar='drag', type=float, default=0.2,
                       help='drag coefficient (default: %(default)s)')
    parser.add_argument('-p', metavar='poolSize', type=int, default=20,
                       help='pool size (default: %(default)s)')
    #parser.print_help()

    args = parser.parse_args(sys.argv[1:])

    learnAscent(args.planet, args.alt0, args.alt1, args.a, args.d, args.p)