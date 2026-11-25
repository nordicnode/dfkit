-- agent/stockpile - create a stockpile and enable categories.
-- usage: agent/stockpile <x0> <y0> <z0> <x1> <y1> <z1> <type> [type...]
local json = require('json')
local buildings = require('dfhack.buildings')
local a = { ... }

local x0, y0, z0 = tonumber(a[1]), tonumber(a[2]), tonumber(a[3])
local x1, y1, z1 = tonumber(a[4]), tonumber(a[5]), tonumber(a[6])
if not x0 or not x1 then
    print('usage: agent/stockpile <x0> <y0> <z0> <x1> <y1> <z1> <type> [type...]')
    return
end
if z0 ~= z1 then
    print('stockpiles must be on one z-level')
    return
end

local ALIASES = {
    drink = 'food', drinks = 'food', meals = 'food',
    logs = 'wood', rock = 'stone', blocks = 'bars_blocks', bars = 'bars_blocks',
    goods = 'finished_goods', clothes = 'cloth',
}

local types = {}
local template_id = nil
for i = 7, #a do
    local name = a[i]:lower()
    if name:sub(1, 9) == 'template=' then
        template_id = tonumber(name:sub(10))
    else
        types[#types + 1] = ALIASES[name] or name
    end
end
if #types == 0 then
    print('no stockpile type given')
    return
end

local width = math.abs(x1 - x0) + 1
local height = math.abs(y1 - y0) + 1
local b, err = buildings.constructBuilding{
    type = df.building_type.Stockpile,
    pos = { x = math.min(x0, x1), y = math.min(y0, y1), z = z0 },
    width = width,
    height = height,
    abstract = true,
}
if not b then
    print('cannot create stockpile: ' .. tostring(err))
    return
end

local applied = {}
for _, name in ipairs(types) do
    if b.settings.flags[name] ~= nil then
        b.settings.flags[name] = true
        applied[#applied + 1] = name
    end
end

-- A freshly created stockpile has category flags but no subtype vectors, and
-- DF only initialises those when a category is first picked in the UI. Copy
-- the vectors from an existing stockpile that the player configured.
local copied = 0
if template_id then
    local src
    for _, x in ipairs(df.global.world.buildings.all) do
        if x.id == template_id then src = x end
    end
    if src and src:getType() == df.building_type.Stockpile then
        for category, flag in pairs(src.settings.flags) do
            if type(flag) == 'boolean' and src.settings.flags[category]
               and src.settings[category] and b.settings[category] then
                for key, vec in pairs(src.settings[category]) do
                    local dst = b.settings[category][key]
                    if type(vec) == 'userdata' and dst and type(dst) == 'userdata' then
                        local ok, n = pcall(function() return #vec end)
                        if ok then
                            dst:resize(0)
                            for j = 0, n - 1 do dst:insert('#', vec[j]) end
                            copied = copied + n
                        end
                    end
                end
            end
        end
    end
end

print(json.encode({
    copied_subtypes = copied,
    id = b.id,
    pos = { b.x1, b.y1, z0 },
    width = width,
    height = height,
    types = applied,
}))
