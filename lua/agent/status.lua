-- agent/status  -  one-shot JSON snapshot for AI agents.
-- Called by dfagent via the DFHack RPC; prints a single JSON object.
--[====[

agent/status
============
Machine-readable fortress status: mode, menu, date, population, idlers,
food and drink, threats and the length of the job queue.

]====]

local json = require('json')

local function viewscreen_name()
    local vs = dfhack.gui.getCurViewscreen()
    if not vs then return 'none' end
    local name = tostring(vs)
    name = name:match('^<([^:]+)') or name
    return name
end

local MODES = { [0] = 'fortress', [1] = 'adventure', [2] = 'legends', [3] = 'title' }

local function game_mode()
    local ok, mode = pcall(function() return df.global.gamemode end)
    if not ok or mode == nil then return 'unknown' end
    return MODES[tonumber(mode)] or tostring(mode)
end

local out = {
    viewscreen = viewscreen_name(),
    game_mode = game_mode(),
    paused = df.global.pause_state,
    year = df.global.cur_year,
    year_tick = df.global.cur_year_tick,
    population = 0,
    dwarves = 0,
    idlers = 0,
    animals = 0,
    threats = 0,
    food = 0,
    drink = 0,
    wood = 0,
    jobs = 0,
    wounded = 0,
    dead = 0,
    citizens = {},
    threat_list = {},
}

if dfhack.isWorldLoaded() then
    local active = df.global.world.units.active
    for _, unit in ipairs(active) do
        if dfhack.units.isAlive(unit) then
            if dfhack.units.isCitizen(unit) then
                out.population = out.population + 1
                if dfhack.units.isDwarf(unit) then
                    out.dwarves = out.dwarves + 1
                    if dfhack.units.isActive(unit) and unit.job.current_job == nil then
                        out.idlers = out.idlers + 1
                    end
                    if unit.health and unit.health.flags and (unit.health.flags.needs_healthcare or unit.health.flags.rq_diagnosis) then
                        out.wounded = out.wounded + 1
                    end
                    out.citizens[#out.citizens + 1] = {
                        id = unit.id,
                        name = dfhack.TranslateName(dfhack.units.getVisibleName(unit)),
                        pos = { unit.pos.x, unit.pos.y, unit.pos.z },
                        idle = unit.job.current_job == nil,
                        job = unit.job.current_job and dfhack.job.getName(unit.job.current_job) or nil,
                    }
                end
            elseif dfhack.units.isActive(unit) then
                if dfhack.units.isOpposedToLife(unit) or dfhack.units.isCrazed(unit)
                   or unit.flags1.active_invader then
                    out.threats = out.threats + 1
                    out.threat_list[#out.threat_list + 1] = {
                        id = unit.id,
                        name = dfhack.TranslateName(dfhack.units.getVisibleName(unit)),
                        pos = { unit.pos.x, unit.pos.y, unit.pos.z },
                    }
                else
                    out.animals = out.animals + 1
                end
            end
        else
            out.dead = out.dead + 1
        end
    end

    -- Count everything a dwarf can eat, not just cooked meals: a fort with
    -- raw plants and meat is not starving even when FOOD (meals) is zero.
    local EDIBLE = {
        [df.item_type.FOOD] = true, [df.item_type.PLANT] = true,
        [df.item_type.MEAT] = true, [df.item_type.FISH] = true,
    }
    if df.item_type.CHEESE then EDIBLE[df.item_type.CHEESE] = true end
    if df.item_type.EGG then EDIBLE[df.item_type.EGG] = true end

    for _, item in ipairs(df.global.world.items.all) do
        local t = item:getType()
        if EDIBLE[t] then
            out.food = out.food + item:getStackSize()
        elseif t == df.item_type.DRINK then
            out.drink = out.drink + item:getStackSize()
        elseif t == df.item_type.WOOD then
            out.wood = out.wood + 1
        end
    end

    pcall(function()
        local head = df.global.world.jobs.list
        local node = head.next
        while node and node ~= head do
            out.jobs = out.jobs + 1
            node = node.next
        end
    end)
end

print(json.encode(out))
