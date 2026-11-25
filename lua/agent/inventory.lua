-- agent/inventory - item counts by type, plus food/drink totals
local json = require('json')
local counts = {}
local food, drink = 0, 0
local EDIBLE = {
    [df.item_type.FOOD] = true, [df.item_type.PLANT] = true,
    [df.item_type.MEAT] = true, [df.item_type.FISH] = true,
}
if df.item_type.CHEESE then EDIBLE[df.item_type.CHEESE] = true end
if df.item_type.EGG then EDIBLE[df.item_type.EGG] = true end

for _, item in ipairs(df.global.world.items.all) do
    local t = item:getType()
    local name = df.item_type[t] or tostring(t)
    counts[name] = (counts[name] or 0) + 1
    if EDIBLE[t] then food = food + item:getStackSize() end
    if t == df.item_type.DRINK then drink = drink + item:getStackSize() end
end

print(json.encode({ counts = counts, food = food, drink = drink }))
