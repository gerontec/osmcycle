SELECT json_agg(json_build_object('trail', trail, 'points', pts))
FROM (
  SELECT trail,
    (SELECT json_agg(json_build_array(round(ST_X(p.geom)::numeric,5), round(ST_Y(p.geom)::numeric,5)))
     FROM ST_DumpPoints(ST_SimplifyPreserveTopology(ST_Transform(way,4326),0.0008)) p) AS pts
  FROM wanderwege WHERE way IS NOT NULL
) s WHERE pts IS NOT NULL;
