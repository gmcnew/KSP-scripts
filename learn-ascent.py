import argparse
import math
import os
import random
import sys

import ascent
import planet

STABLE_ITERATIONS = 1000

# Using an end angle other than 0 is actually not very helpful.
VARY_END_ANGLE = False

class Profile:

    # Class variables.
    planet = None
    alt0   = None
    alt1   = None
    accel  = None
    drag   = None

    cache = {}
    MAX_CACHE_SIZE = 10000

    def __init__(self, gt0, gt1, curve, endAngle):
        # Limit precision of values.
        (gt0, gt1, endAngle) = [round(x, 2) for x in (gt0, gt1, endAngle)]
        curve = round(curve, 3)

        self.gt0        = min(max(gt0,        0), self.alt1)
        self.gt1        = min(max(gt1,        0), self.alt1)
        self.curve      = min(max(curve,      0), 1)
        self.endAngle   = min(max(endAngle, -10), 90) if VARY_END_ANGLE else 0

        self.ascent     = None

        self.score = self.cache.get((self.gt0, self.gt1, self.curve, self.endAngle), None)
        if self.score is None:
            if len(self.cache) == self.MAX_CACHE_SIZE:
                del self.cache[random.choice(self.cache.keys())]
            self._calc_score()
            self.cache[(self.gt0, self.gt1, self.curve, self.endAngle)] = self.score

        self.generation = 1

    @classmethod
    def init(cls, planet, alt0, alt1, accel, drag):
        cls.planet = planet
        cls.alt0   = alt0
        cls.alt1   = alt1
        cls.accel  = accel
        cls.drag   = drag

    @classmethod
    def clear_cache(cls):
        cls.cache = {}

    @classmethod
    def from_string(cls, str):
        tokens = [float(f) for f in str.strip().split(" ")]
        if len(tokens) == 5:
            tokens.append(-1)
        (gt0, gt1, curve, endAngle, score) = tokens[:5]
        return Profile(gt0, gt1, curve, endAngle)

    #9.72 23.87 0.3381 1119.067026
    @classmethod
    def random(cls):
        gt0 = random.random() * (cls.alt1 / 2)
        gt1 = gt0 + random.random() * (cls.alt1 - gt0)
        curve = random.random() * 2
        endAngle = random.random() * 90
        return Profile(gt0, gt1, curve, endAngle)

    def mutated(self):
        vals = [self.gt0, self.gt1, self.curve, self.endAngle]
        i = random.randint(0, len(vals) - 1)
        vals[i] = self._mutate(vals[i])
        return Profile(vals[0], vals[1], vals[2], vals[3])

    def _mutate(self, value):
        amount = 0.1

        # Mutate more slowly in later generations.
        #amount /= math.log(self.generation + 1)

        return value + (random.random() - 0.5) * (math.sqrt(math.fabs(value)) if value else 1) * amount

    def _calc_score(self):
        try:
            self.ascent = ascent.climbSlope(self.planet,
                    orbitAltitude       = self.alt1 * 1000,
                    gravityTurnStart    = self.gt0 * 1000,
                    gravityTurnEnd      = self.gt1 * 1000,
                    gravityTurnCurve    = self.curve,
                    acceleration        = self.planet.gravity() * self.accel,
                    initialAltitude     = self.alt0 * 1000,
                    dragCoefficient     = self.drag,
                    endAngleDeg         = self.endAngle
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
        return Profile(self._combine(self.gt0,      other.gt0),
                       self._combine(self.gt1,      other.gt1),
                       self._combine(self.curve,    other.curve),
                       self._combine(self.endAngle, other.endAngle))

    def better_than(self, other):
        return (not other) or other.score < 0 or (self.score > 0 and self.score < other.score)

    def worse_than(self, other):
        return (not other) or self.score > other.score

    def __str__(self):
        return "%.2f %.2f %.3f %.2f %f" % (self.gt0, self.gt1, self.curve, self.endAngle, self.score)

    def guide(self):
        angleStep = 15
        guide = ""
        if self.curve:
           guide = "angle  altitude"
           for angle in range(0, 90 + 1, angleStep):
               dy = self.gt1 - self.gt0
               alt = self.gt0 + ((float(angle) / 90) ** (1.0 / self.curve)) * dy
               guide += "\n%5d  %8.1f" % (angle, alt)
        return guide

    @classmethod
    def desc_header(cls):
        header = "start    end shape"
        if VARY_END_ANGLE:
            header += " endAng"
        header += "   deltaV"
        header += "  loss_g     atm  steer"
        return header

    def desc(self):
        desc = ""
        desc += "%5.2f %6.2f %5.1f " % (self.gt0, self.gt1, self.curve * 100)
        if VARY_END_ANGLE:
            desc += "%6.2f " % self.endAngle
        desc += "%8.2f " % self.score
        desc += "%7.2f %7.2f %6.2f" % (self.ascent.loss_gravity, self.ascent.loss_drag, self.ascent.loss_steering)
        return desc

def select(pool, s):
    for profile in pool:
        if random.random() > s:
            return profile
    return pool[-1]

SILENT = True

def learnAscent(planetName, startAlt = 0, endAlt = None, accel = 2, drag = 0.2, poolSize = 20, fileIn = None, genLimit = None):

    p = planet.planets[planetName.lower()]

    if endAlt is None:
        endAlt = math.ceil(p.topOfAtmosphere() / 5000) * 5

    if not SILENT:
        print("ascending on %s from %d to %d km" % (p, startAlt, endAlt))
        print("max acceleration: %.2f x surface gravity = %.2f m/s^2" % (accel, accel * p.gravity()))
        if drag != 0.2:
            print("drag coefficient: %.2f" % drag)
    Profile.init(p, startAlt, endAlt, accel, drag)

    fileOut = "%s_%d_%d_%.2f_%.2f.txt" % (p.name, startAlt, endAlt, accel, drag)

    if fileIn is None:
        fileIn = fileOut

    pool = []

    if fileIn and os.path.exists(fileIn) and not SILENT:
        with open(fileIn) as f:
            for line in f.readlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    pool.append(Profile.from_string(line))

    while len(pool) < poolSize:
        profile = Profile.random()
        pool.append(profile)

    bestEver = None
    gen = 1
    lastChange = 0
    needNewline = False

    bestThisRound = None
    if not SILENT:
        print("%6s %s" % ("iter", Profile.desc_header()))
    try:
        while True:
            best = None
            worst = None
            total = 0
            successes = 0
            candidates = []
            for profile in pool:
                profile.generation = gen
                if profile.better_than(best):
                    if profile.better_than(bestEver):
                        bestEver = profile
                    best = profile
                    if profile.better_than(bestThisRound):
                        lastChange = gen
                        bestThisRound = profile

                if profile.worse_than(worst):
                    worst = profile

                if profile.score > 0:
                    total += profile.score
                    successes += 1
                    candidates.append(profile)
            candidates.sort()
            if successes and not SILENT:
                lineOut = "\r%6d %s" % (gen, bestEver.desc())
                sys.stdout.write(lineOut)
                sys.stdout.flush()
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

            if gen >= lastChange + STABLE_ITERATIONS:
                #print("\n%6d stable iterations; resetting..." % STABLE_ITERATIONS)
                Profile.clear_cache()
                newPool = []
                lastChange = gen
                bestThisRound = None

            while len(newPool) < poolSize:
                newPool.append(Profile.random())
            pool = newPool

            gen += 1
            if genLimit is not None and gen >= genLimit:
                break

    except KeyboardInterrupt:
        print("")
        pool.append(bestEver)
        pool.sort()
        with open(fileOut, "w") as f:
            for profile in pool:
                f.write("%s\n" % profile)
        print("")
        print(bestEver.guide())

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description = "Learn an ascent.")
    args = [
        ('planet',    'planet',   str,   None, 'planet or moon'),
        ('alt0',      'alt0',     int,   None, 'initial altitude (km)'),
        ('alt1',      'alt1',     int,   None, 'final altitude (km)'),
        ('-a',        'accel',    float, 2.2,  'ship acceleration as a multiple of planet surface gravity (default: %(default)s)'),
        ('-d',        'drag',     float, 0.2,  'drag coefficient (default: %(default)s)'),
        ('-p',        'poolSize', int,   2,    'pool size (default: %(default)s)'),
        ('--profile', 'filename', str,   None, 'profile one generation of execution and save results'),
        ]
    for (name, metavar, type, default, help) in args:
        parser.add_argument(name, metavar=metavar, type=type, help=help, default=default)

    args = parser.parse_args(sys.argv[1:])

    if args.profile:
        random.seed(0)
        import cProfile
        SILENT = True
        cProfile.run('learnAscent(args.planet, args.alt0, args.alt1, args.a, args.d, args.p, genLimit = 5)', args.profile)
    else:
        SILENT = False
        learnAscent(args.planet, args.alt0, args.alt1, args.a, args.d, args.p)
