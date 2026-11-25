-- agent/deconstruct <building_id>
local json = require('json')
local buildings = require('dfhack.buildings')
local id = tonumber(({ ... })[1])
local function find(id) for _, b in ipairs(df.global.world.buildings.all) do if b.id == id then return b end end end
local b = find(id)
if not b then print(json.encode({ ok = false, error = 'no such building' })) return end
local ok = buildings.deconstruct(b)
print(json.encode({ ok = ok and true or false, id = id }))
