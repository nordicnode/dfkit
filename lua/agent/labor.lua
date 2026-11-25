-- agent/labor <labor> <on|off> - set a labor for every citizen
local json = require('json')
local a = { ... }
local name = (a[1] or ''):upper()
local enable = (a[2] or 'on') == 'on'
local index
for i = 0, df.unit_labor._last_item do
    if df.unit_labor[i] == name then index = i end
end
if not index then
    print('unknown labor: ' .. name)
    return
end
local changed = 0
for _, u in ipairs(df.global.world.units.active) do
    if dfhack.units.isCitizen(u) and dfhack.units.isDwarf(u) then
        if u.status.labors[index] ~= enable then
            u.status.labors[index] = enable
            changed = changed + 1
        end
    end
end
print(json.encode({ labor = name, enabled = enable, changed = changed }))
