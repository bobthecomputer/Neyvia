export function asSchemaRecord(value) {
  return value && typeof value === "object" && !Array.isArray(value) ? value : {};
}

export function schemaArgumentProperties(schema) {
  return Object.entries(asSchemaRecord(asSchemaRecord(schema).properties));
}

export function schemaRequiredArguments(schema) {
  return new Set(
    (Array.isArray(asSchemaRecord(schema).required) ? schema.required : []).map(String),
  );
}

function parseSchemaField(raw, schema) {
  const type = String(schema?.type || "string");
  if (type === "boolean") return Boolean(raw);
  if (raw === "" || raw == null) return undefined;
  if (type === "integer") {
    const value = Number(raw);
    if (!Number.isInteger(value)) throw new Error("must be an integer");
    return value;
  }
  if (type === "number") {
    const value = Number(raw);
    if (!Number.isFinite(value)) throw new Error("must be a number");
    return value;
  }
  if (type === "object" || type === "array") {
    try {
      const value = JSON.parse(String(raw));
      if (type === "array" && !Array.isArray(value)) throw new Error("must be a JSON array");
      if (type === "object" && (value == null || Array.isArray(value) || typeof value !== "object")) {
        throw new Error("must be a JSON object");
      }
      return value;
    } catch (error) {
      throw new Error(error instanceof Error ? error.message : "must be valid JSON");
    }
  }
  return String(raw);
}

export function buildSchemaArguments(schema, values = {}, extraArguments = "") {
  const properties = schemaArgumentProperties(schema);
  const required = schemaRequiredArguments(schema);
  const result = {};
  for (const [name, fieldSchema] of properties) {
    let value;
    try {
      value = parseSchemaField(values[name], fieldSchema);
    } catch (error) {
      throw new Error(`${name} ${error instanceof Error ? error.message : "is invalid"}`);
    }
    if (value === undefined) {
      if (required.has(name)) throw new Error(`${name} is required`);
      continue;
    }
    result[name] = value;
  }
  if (String(extraArguments || "").trim()) {
    const extra = JSON.parse(extraArguments);
    if (!extra || typeof extra !== "object" || Array.isArray(extra)) {
      throw new Error("Additional arguments must be a JSON object");
    }
    Object.assign(result, extra);
  }
  return result;
}
