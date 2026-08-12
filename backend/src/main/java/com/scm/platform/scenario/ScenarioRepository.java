package com.scm.platform.scenario;

import com.scm.platform.scenario.ScenarioController.ScenarioType;
import com.scm.platform.scenario.ScenarioController.ScenarioView;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@Repository
public class ScenarioRepository {

	private static final String COLUMNS = "scenario_id, name, scenario_type, parameters::text AS parameters, created_at";

	private final JdbcClient jdbc;

	private final JsonMapper json;

	private final RowMapper<ScenarioView> mapper;

	public ScenarioRepository(JdbcClient jdbc, JsonMapper json) {
		this.jdbc = jdbc;
		this.json = json;
		this.mapper = (rs, i) -> new ScenarioView(rs.getString("scenario_id"), rs.getString("name"),
				ScenarioType.valueOf(rs.getString("scenario_type")), this.json.readTree(rs.getString("parameters")),
				rs.getObject("created_at", OffsetDateTime.class).toInstant());
	}

	public void insert(String id, String name, ScenarioType type, JsonNode parameters) {
		jdbc.sql("INSERT INTO scenario (scenario_id, name, scenario_type, parameters, created_at)"
				+ " VALUES (:id, :name, :type, CAST(:parameters AS jsonb), now())")
				.param("id", id).param("name", name).param("type", type.name())
				.param("parameters", parameters.toString()).update();
	}

	public Optional<ScenarioView> find(String id) {
		return jdbc.sql("SELECT " + COLUMNS + " FROM scenario WHERE scenario_id = :id").param("id", id)
				.query(mapper).optional();
	}

	public List<ScenarioView> list() {
		return jdbc.sql("SELECT " + COLUMNS + " FROM scenario ORDER BY created_at DESC, scenario_id").query(mapper)
				.list();
	}

}
