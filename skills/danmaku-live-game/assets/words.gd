class_name Words
extends RefCounted
## Theme layer (docs/DESIGN.md section 13). Every player-facing word comes from
## config/theme_<id>.json so the same rules can ship under another theme. Rules keep ids;
## this maps ids to names, verbs to danmaku keywords and message keys to templates.
## (Not called Theme: that name belongs to Godot's built-in Theme resource.)
##   Words.text("sign.done", [20, "聚气丹"])  -> the template % args
##   Words.name("item", "herb")               -> 灵草
##   Words.keys("explore")                    -> ["摸索"]
## A theme may "extends" another one and override only some keys. Strings may embed
## {term}, {group.id} (a name) and {cmd.verb} (the first keyword); they are filled in at load,
## so renaming 灵石 in "terms" renames it in every message.

const DEFAULT_THEME := "xianxia"
const _SECTIONS := ["terms", "names", "commands", "text"]

static var _id := ""
static var _data: Dictionary = {}
static var _token: RegEx


## Switches the theme for the whole game (startup, and tests that try another theme).
static func use(theme_id: String) -> void:
	_id = theme_id
	_data = _load(theme_id)
	for section in _SECTIONS:
		if not _data.has(section):
			_data[section] = {}
	for i in 3:  # names can use terms, texts can use names
		for section in ["terms", "names", "text"]:
			_data[section] = _fill(_data[section])


## The theme chosen in config/game.json ("theme"), or xianxia.
static func configured() -> String:
	var config: Variant = JSON.parse_string(FileAccess.get_file_as_string("res://config/game.json"))
	return str(config.get("theme", DEFAULT_THEME)) if config is Dictionary else DEFAULT_THEME


static func current() -> String:
	_ensure()
	return _id


## Message template, formatted with `args` when given (so a template without args keeps a literal %).
static func text(key: String, args: Array = []) -> String:
	_ensure()
	var template: String = str(_data.text.get(key, key))
	return template if args.is_empty() else template % args


static func term(key: String) -> String:
	_ensure()
	return str(_data.terms.get(key, key))


## Display name of an id in a names group. Array groups take an index.
static func name(group: String, id: Variant) -> String:
	var table: Variant = names(group)
	if table is Array:
		var index := int(id)
		return str(table[index]) if index >= 0 and index < table.size() else str(id)
	if table is Dictionary:
		return str(table.get(str(id), id))
	return str(id)


## A whole names group: Array (indexed) or Dictionary (by id).
static func names(group: String) -> Variant:
	_ensure()
	return _data.names.get(group, {})


## The id (Dictionary group) whose name is `display`, or "".
static func id_of(group: String, display: String) -> String:
	var table: Variant = names(group)
	if table is Dictionary:
		for id in table:
			if str(table[id]) == display:
				return str(id)
	return ""


## The index (Array group) whose name is `display`, or -1.
static func index_of(group: String, display: String) -> int:
	var table: Variant = names(group)
	return table.find(display) if table is Array else -1


## Danmaku keywords for a verb; the first one is what hints show.
static func keys(verb: String) -> Array:
	_ensure()
	return _data.commands.get(verb, [])


static func key(verb: String) -> String:
	var all := keys(verb)
	return str(all[0]) if not all.is_empty() else verb


## Folder under assets/themes/ searched before assets/generated/.
static func art_dir() -> String:
	_ensure()
	return str(_data.get("art", _id))


static func _ensure() -> void:
	if _data.is_empty():
		use(configured())


static func _load(theme_id: String) -> Dictionary:
	var path := "res://config/theme_%s.json" % theme_id
	var parsed: Variant = JSON.parse_string(FileAccess.get_file_as_string(path)) if FileAccess.file_exists(path) else null
	if not parsed is Dictionary:
		push_error("theme not found or invalid: " + path)
		return {} if theme_id == DEFAULT_THEME else _load(DEFAULT_THEME)
	var base: String = str(parsed.get("extends", ""))
	if base.is_empty():
		return parsed
	return _merge(_load(base), parsed)


## Dictionaries merge key by key; anything else (strings, lists) is replaced whole.
static func _merge(base: Dictionary, over: Dictionary) -> Dictionary:
	var result := base.duplicate(true)
	for k in over:
		if result.get(k) is Dictionary and over[k] is Dictionary:
			result[k] = _merge(result[k], over[k])
		else:
			result[k] = over[k]
	return result


static func _fill(value: Variant) -> Variant:
	if value is String:
		return _fill_string(value)
	if value is Array:
		return value.map(func(v): return _fill(v))
	if value is Dictionary:
		var result := {}
		for k in value:
			result[k] = _fill(value[k])
		return result
	return value



static func _fill_string(source: String) -> String:
	if not source.contains("{"):
		return source
	if _token == null:
		_token = RegEx.create_from_string("\\{([a-z_]+)(?:\\.([a-z0-9_]+))?\\}")
	var result := source
	for found in _token.search_all(source):
		var group := found.get_string(1)
		var id := found.get_string(2)
		var replacement: Variant = null
		if id.is_empty():
			replacement = _data.terms.get(group)
		elif group == "cmd":
			var words: Array = _data.commands.get(id, [])
			replacement = words[0] if not words.is_empty() else null
		else:
			var table: Variant = _data.names.get(group)
			if table is Array and id.is_valid_int() and int(id) < table.size():
				replacement = table[int(id)]
			elif table is Dictionary:
				replacement = table.get(id)
		if replacement is String:
			result = result.replace(found.get_string(), replacement)
	return result
