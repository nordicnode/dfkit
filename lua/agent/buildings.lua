-- agent/buildings - workshop/noble state as JSON
local json = require('json')

local out = {
    workshops = {},
    furnaces = {},
    manager = false,
    orders = 0,
    beds = 0,
    tables = 0,
    farms = 0,
}

local function add(bucket, enum, value)
    local name = enum[value]
    name = name and name:lower() or ("type_" .. tostring(value))
    bucket[name] = (bucket[name] or 0) + 1
end

out.workshop_list = {}
out.stockpiles = {}

for _, b in ipairs(df.global.world.buildings.all) do
    local t = b:getType()
    if t == df.building_type.Workshop then
        add(out.workshops, df.workshop_type, b.type)
        local name = df.workshop_type[b.type]
        out.workshop_list[#out.workshop_list + 1] = {
            id = b.id,
            type = name and name:lower() or tostring(b.type),
            pos = { b.centerx, b.centery, b.z },
        }
    elseif t == df.building_type.Furnace then
        add(out.furnaces, df.furnace_type, b.type)
    elseif t == df.building_type.Farm then
        out.farms = out.farms + 1
    elseif t == df.building_type.Stockpile then
        out.stockpiles[#out.stockpiles + 1] = {
            id = b.id,
            pos = { b.x1, b.y1, b.z },
            width = b.room.width,
            height = b.room.height,
        }
    elseif t == df.building_type.Bed then
        out.beds = out.beds + 1
    elseif t == df.building_type.Table then
        out.tables = out.tables + 1
    end
end

local ok, entity = pcall(function()
    return df.historical_entity.find(df.global.ui.group_id)
end)
if ok and entity then
    -- DFHack's assignments_by_type cache is not maintained in 0.47.05, so
    -- resolve the MANAGER position and its assignment directly.
    for _, pos in ipairs(entity.positions.own) do
        if pos.code == 'MANAGER' then
            for _, a in ipairs(entity.positions.assignments) do
                if a.position_id == pos.id and a.histfig ~= -1 then
                    out.manager = true
                end
            end
        end
    end
end

out.orders = #df.global.world.manager_orders
print(json.encode(out))
