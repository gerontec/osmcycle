-- Copernicus GLO-30 elevation model, stored as raster blocks.
-- See docs/ELEVATION.md for the reasoning; server/dem/dem_import.py fills it.
--
-- Why blocks and not one row per elevation point: Bayern + Tirol + Südtirol +
-- Kärnten hold ~389 million samples at 1 arc second. As rows that is tens of GB
-- plus an index bigger than the payload. As 256x256 int16 patches it is 319 MB,
-- and a point query touches exactly one block.
--
--   mysql -u <user> -p <database> < schema.sql

CREATE TABLE IF NOT EXISTS dem_tile (
  lat_deg    TINYINT  NOT NULL COMMENT 'SW corner of the 1-degree cell',
  lon_deg    TINYINT  NOT NULL,
  width      SMALLINT UNSIGNED NOT NULL COMMENT 'columns: 2400 above 50N, else 3600',
  height     SMALLINT UNSIGNED NOT NULL,
  origin_lat DOUBLE   NOT NULL COMMENT 'centre of pixel (0,0), i.e. top-left',
  origin_lon DOUBLE   NOT NULL,
  px_lat     DOUBLE   NOT NULL COMMENT 'step per pixel, negative (southwards)',
  px_lon     DOUBLE   NOT NULL COMMENT 'above 50N Copernicus uses 1.5", not 1"',
  blocksize  SMALLINT UNSIGNED NOT NULL COMMENT 'edge length of a dem_block, 256',
  PRIMARY KEY (lat_deg, lon_deg)
) ENGINE=InnoDB COMMENT='Copernicus GLO-30: georeference per 1-degree tile';

CREATE TABLE IF NOT EXISTS dem_block (
  lat_deg TINYINT  NOT NULL,
  lon_deg TINYINT  NOT NULL,
  brow    SMALLINT UNSIGNED NOT NULL COMMENT 'block row inside the tile',
  bcol    SMALLINT UNSIGNED NOT NULL,
  data    MEDIUMBLOB NOT NULL
          COMMENT 'zlib(int16 little-endian, row-major, 256x256); -32768 = nodata',
  PRIMARY KEY (lat_deg, lon_deg, brow, bcol)
) ENGINE=InnoDB COMMENT='Copernicus GLO-30: 256x256 raster blocks, ~60 kB each';
