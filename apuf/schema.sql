CREATE TABLE IF NOT EXISTS studies (
    study_id INTEGER PRIMARY KEY,

    device_id TEXT NOT NULL,
    slice TEXT NOT NULL,
    stages INTEGER NOT NULL,

    challenge_md5 TEXT NOT NULL,
    placement_variant TEXT NOT NULL,
    placement_gap INTEGER NOT NULL,
    placement_offset INTEGER NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,

    UNIQUE(
        device_id,
        slice,
        stages,
        challenge_md5,
        placement_variant,
        placement_gap,
        placement_offset
    )
);

CREATE TABLE IF NOT EXISTS acquisitions (
    acquisition_id INTEGER PRIMARY KEY,

    study_id INTEGER NOT NULL,
    started_at TEXT NOT NULL,

    FOREIGN KEY(study_id)
        REFERENCES studies(study_id)
);

CREATE TABLE IF NOT EXISTS crps (
    acquisition_id INTEGER NOT NULL,
    sample_id INTEGER NOT NULL,
    challenge_id INTEGER NOT NULL,
    response INTEGER NOT NULL,

    PRIMARY KEY (
        acquisition_id,
        sample_id,
        challenge_id
    ),

    FOREIGN KEY(acquisition_id)
        REFERENCES acquisitions(acquisition_id)
) WITHOUT ROWID;
