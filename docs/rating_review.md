# Rating review (PLAN §2.4)

Manual sanity check of the composite player score (`player_scores.csv`,
`src/features/player_scores.py`) for the six football-literate-test nations before
the ratings feed the squad indices. One absurd rating destroys credibility regardless
of Brier score, so this is a gate, not a formality.

**Score is position-normalised** ("how good for his position, vs the 2026 field"), the
form the §3 indices need — read the lists as *within-position* standing, not absolute
impact. Date: 2026-06-15.

## Per-nation verdict (top of each squad)

- **ARG — pass.** Lautaro 98, Cristian Romero 98, Emi Martínez 96, Julián Álvarez 94,
  then Molina / Mac Allister / Enzo. The spine is exactly right.
- **GER — pass.** Musiala 99, Kimmich 96, Wirtz 90, Sané, Schlotterbeck. Right.
- **BRA — pass on those rated.** Bruno Guimarães 96, Raphinha 96, Vinícius Jr 93,
  Martinelli, Paquetá, Endrick, Alisson. **Coverage: 19/26 carry a market value**, the
  7 without are absent from the scrape (see below).
- **FRA — pass.** Mbappé 99 top (was unrated until the captain-name fix), then Théo
  Hernández, Olise, Dembélé, Doué, Koundé, Upamecano.
- **ENG — pass.** Saka 92, Rashford 92, Reece James 90, Kane 87, Bellingham 84, Rice
  83, Pickford. Spread sensible.
- **SWE — pass.** Gyökeres and Isak both high (75M each, the names a Swede checks
  first). Caveat: the #1 GK (Johansson) edges them — position-normalisation artifact,
  not an error (see below).

No absurd outfield ratings remain after the captain fix. The marquee stars land where a
fan expects them *within their position*.

## Issues logged (not blockers, but real)

1. **Coverage gaps are data-absence, not name mismatches — investigated 2026-06-16.**
   With the name-overrides already in place (Gabriel Magalhães, Éderson, Danilo Luiz, …),
   135 of 1248 players carry no market value (`name_unmatched_squad_transfermarkt.csv`);
   Brazil is 19/26. The remainder are genuinely absent from Transfermarkt's national-team
   page snapshot — fringe/uncapped or minor-league call-ups, plus stars in non-scraped
   leagues (Neymar, Bremer, Roger Ibañez). A second name-overrides pass recovers ~0: the
   residual candidates are coincidental common-name collisions (`Gessime Yassine` ≠
   `Yassine Bounou`; `Issa Diop` ≠ `Sofiane Diop`; the squad's two distinct `Danilo`s —
   Luiz the DF is mapped, Santos the MF isn't in the scrape), and mapping them would inject
   a wrong value, worse than a missing one. Recovery needs per-player TM profile scrapes,
   not overrides. Not forecast-relevant either — the live model is Elo + market only and the
   player indices don't feed it.

2. **Cross-position "top player" lists over-surface keepers.** Because the score is
   position-normalised, a squad's best-in-a-thin-GK-pool keeper can outscore a good-
   but-not-elite forward (Sweden: Johansson > Gyökeres). GK scores overall are
   well-distributed (mean ~48, same as FW), so this is a *display* concern, not an
   index bug. For fan surfaces, rank within position or carry a separate absolute
   display score; the indices are unaffected.

3. **Predicted VAEP is uninformative for keepers** (GKs barely register VAEP), so its
   0.15 weight injects noise into GK ratings (pred percentile ~0.9+ for several
   backups). Cheap refinement: drop the predicted term for `pos_group == "GK"`.

4. **Market value carries a youth premium.** Young high-fee players (Zaïre-Emery,
   Malo Gusto, Endrick, Doué) rate above some established names. Inherited from the
   market (the backbone signal), defensible, noted.

## Actions

- [x] Investigated the 135 market-value unmatched (BRA + African squads, 2026-06-16):
      data-absence from the TM national-team scrape, not name mismatches — a safe overrides
      pass recovers ~0 (issue 1). Per-player TM profile scrapes are the only recovery; not
      forecast-relevant, so deferred.
- [ ] Consider per-position display ranking and dropping the GK predicted term.
- These are refinements; the ratings are good enough to proceed to §3 indices.
