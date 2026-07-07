-- Build the Tiroler Höhenweg by routing along OSM trails through the huts.
\set ON_ERROR_STOP on

-- 1. hiking trails in the corridor (trails only -> smaller graph)
DROP TABLE IF EXISTS hike_edges, hike_noded, hike_vertices CASCADE;
CREATE TABLE hike_edges AS
SELECT osm_id AS id, way AS geom
FROM planet_osm_line
WHERE highway IN ('path','footway','track','steps','bridleway','service','unclassified','residential','pedestrian')
  AND way && ST_Transform(ST_MakeEnvelope(10.90,46.64,11.95,47.20,4326),3857);

-- 2. node the network at intersections (split through-ways at junctions)
CREATE TABLE hike_noded AS
SELECT row_number() OVER () AS id,
       geom,
       ST_Length(geom) AS cost,
       ST_Length(geom) AS reverse_cost,
       NULL::bigint AS source, NULL::bigint AS target
FROM (SELECT (ST_Dump(ST_UnaryUnion(ST_Collect(geom)))).geom AS geom FROM hike_edges) s
WHERE ST_GeometryType(geom) = 'ST_LineString' AND ST_Length(geom) > 0;

-- 3. topology: vertices + source/target
CREATE TABLE hike_vertices AS
SELECT id, geom FROM pgr_extractVertices('SELECT id, geom FROM hike_noded');
CREATE INDEX ON hike_vertices USING gist(geom);
CREATE INDEX ON hike_noded USING gist(geom);
UPDATE hike_noded e SET source = v.id FROM hike_vertices v WHERE ST_StartPoint(e.geom) = v.geom;
UPDATE hike_noded e SET target = v.id FROM hike_vertices v WHERE ST_EndPoint(e.geom)   = v.geom;

SELECT count(*) AS trail_edges, count(source) AS with_topo FROM hike_noded;

-- 4. ordered hut anchors -> nearest graph vertex
DROP TABLE IF EXISTS tirol_anchors;
CREATE TABLE tirol_anchors(seq int, name text, lon float, lat float);
INSERT INTO tirol_anchors VALUES
 (1,'Mayrhofen',11.8639,47.1672),
 (2,'Sattelbergalm',11.4933,47.0204),
 (3,'Tribulaunhütte',11.3256,46.9857),
 (4,'St. Martin am Schneeberg',11.1809,46.8989),
 (5,'Zwickauer Hütte',11.0550,46.8018),
 (6,'Stettiner Hütte',11.0288,46.7571),
 (7,'Bockerhütte',11.1195,46.7264),
 (8,'Meran',11.1596,46.6713);

DROP TABLE IF EXISTS tirol_vids;
CREATE TABLE tirol_vids AS
SELECT a.seq,
       (SELECT v.id FROM hike_vertices v
        ORDER BY v.geom <-> ST_Transform(ST_SetSRID(ST_MakePoint(a.lon,a.lat),4326),3857)
        LIMIT 1) AS vid
FROM tirol_anchors a ORDER BY a.seq;

-- 5. route through the huts in order and store the path geometry
DROP TABLE IF EXISTS tirol_path;
CREATE TABLE tirol_path AS
SELECT n.geom
FROM pgr_dijkstraVia(
       'SELECT id, source, target, cost, reverse_cost FROM hike_noded',
       (SELECT array_agg(vid ORDER BY seq) FROM tirol_vids),
       directed := false
     ) d
JOIN hike_noded n ON n.id = d.edge
WHERE d.edge > 0;

SELECT count(*) AS path_edges, round(ST_Length(ST_Collect(geom))/1000) AS km FROM tirol_path;

-- 6. add into the wanderwege overlay as trail = 'tirol'
DELETE FROM wanderwege WHERE trail = 'tirol';
INSERT INTO wanderwege(trail, name, way)
SELECT 'tirol', 'Tiroler Höhenweg', geom FROM tirol_path;
GRANT SELECT ON wanderwege TO "_renderd";
SELECT trail, count(*) FROM wanderwege GROUP BY trail ORDER BY trail;
