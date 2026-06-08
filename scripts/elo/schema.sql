PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS events (
  event_id      INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  store         TEXT,
  location      TEXT,
  event_date    TEXT,
  season        TEXT,
  num_players   INTEGER,
  status        TEXT,
  notes         TEXT,
  is_ignored    INTEGER NOT NULL DEFAULT 0,
  platform      TEXT NOT NULL DEFAULT 'rph',
  ingested_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_events_date   ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_season ON events(season);

CREATE TABLE IF NOT EXISTS players (
  player_id          INTEGER PRIMARY KEY AUTOINCREMENT,
  display_name       TEXT NOT NULL,
  platform           TEXT NOT NULL DEFAULT 'rph',
  external_username  TEXT,
  merged_into_id     INTEGER REFERENCES players(player_id),
  first_event_id     INTEGER REFERENCES events(event_id),
  created_at         TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(platform, display_name)
);

CREATE TABLE IF NOT EXISTS matches (
  match_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  event_id        INTEGER NOT NULL REFERENCES events(event_id),
  round_id        INTEGER NOT NULL,
  round_number    INTEGER NOT NULL,
  round_type      TEXT,
  table_number    INTEGER,
  player1_id      INTEGER NOT NULL REFERENCES players(player_id),
  player2_id      INTEGER          REFERENCES players(player_id),
  winner_id       INTEGER          REFERENCES players(player_id),
  games_won_p1    INTEGER,
  games_won_p2    INTEGER,
  is_bye          INTEGER NOT NULL DEFAULT 0,
  source          TEXT NOT NULL DEFAULT 'api',
  UNIQUE(event_id, round_id, table_number, player1_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_event  ON matches(event_id);
CREATE INDEX IF NOT EXISTS idx_matches_round  ON matches(round_id);
CREATE INDEX IF NOT EXISTS idx_matches_p1     ON matches(player1_id);
CREATE INDEX IF NOT EXISTS idx_matches_p2     ON matches(player2_id);

CREATE TABLE IF NOT EXISTS ratings (
  rating_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  player_id        INTEGER NOT NULL REFERENCES players(player_id),
  match_id         INTEGER NOT NULL REFERENCES matches(match_id),
  rating_before    REAL NOT NULL,
  rating_after     REAL NOT NULL,
  opponent_id      INTEGER REFERENCES players(player_id),
  opponent_rating  REAL,
  k_factor         REAL NOT NULL,
  score            REAL NOT NULL,
  computed_at      TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_ratings_player ON ratings(player_id);
CREATE INDEX IF NOT EXISTS idx_ratings_match  ON ratings(match_id);

CREATE TABLE IF NOT EXISTS gap_rounds (
  event_id              INTEGER NOT NULL REFERENCES events(event_id),
  round_id              INTEGER NOT NULL,
  round_number          INTEGER NOT NULL,
  phase_type            TEXT,
  expected_matches      INTEGER,
  filled_matches        INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (event_id, round_id)
);
CREATE INDEX IF NOT EXISTS idx_gap_rounds_event ON gap_rounds(event_id);
