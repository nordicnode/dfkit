-- agent/watch - stream game events to dfkit-events.jsonl
-- Registers eventful handlers so the Python daemon can react to incidents
-- instead of polling blindly.
local json = require('json')
local eventful = require('plugins.eventful')

local PATH = dfhack.getDFPath() .. '/dfkit-events.jsonl'

local function emit(kind, data)
    local fh = io.open(PATH, 'a')
    if not fh then return end
    data.kind = kind
    data.tick = df.global.cur_year_tick
    fh:write(json.encode(data), '\n')
    fh:close()
end

eventful.enableEvent(eventful.eventType.JOB_COMPLETED, 1)
eventful.enableEvent(eventful.eventType.UNIT_DEATH, 1)
eventful.enableEvent(eventful.eventType.REPORT, 1)
eventful.enableEvent(eventful.eventType.INVASION, 1)
eventful.enableEvent(eventful.eventType.NEW_UNIT_ACTIVE, 1)

eventful.onJobCompleted.agentWatch = function(job)
    emit('job_completed', {
        job_type = df.job_type[job.job_type] or tostring(job.job_type),
        reaction = job.reaction_name or '',
    })
end

eventful.onUnitDeath.agentWatch = function(unit)
    emit('unit_death', {
        id = unit.id,
        name = dfhack.TranslateName(dfhack.units.getVisibleName(unit)),
        citizen = dfhack.units.isCitizen(unit),
    })
end

eventful.onReport.agentWatch = function(report)
    local text = report.text or ''
    if text ~= '' then emit('report', { text = text }) end
end

eventful.onInvasion.agentWatch = function(inv)
    emit('invasion', {
        race = df.creature_raw.find(inv.race).creature_id,
    })
end

eventful.onUnitNewActive.agentWatch = function(unit)
    if dfhack.units.isOpposedToLife(unit) then
        emit('hostile_spawn', {
            id = unit.id,
            name = dfhack.TranslateName(dfhack.units.getVisibleName(unit)),
        })
    end
end

print(json.encode({ watching = true, path = PATH }))
