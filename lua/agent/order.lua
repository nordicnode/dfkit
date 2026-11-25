-- agent/order - queue a manager order without relying on the stale
-- assignments_by_type cache used by the workorder script.
-- usage: agent/order <JobType> [amount] [reaction_name]
local json = require('json')
local args = { ... }
local job = args[1]
local amount = tonumber(args[2]) or 1
local reaction = args[3]

if not job or job == '' then
    print('usage: agent/order <JobType> [amount] [reaction]')
    return
end

local job_type = df.job_type[job]
if job_type == nil then
    print('unknown job type: ' .. job)
    return
end

local world = df.global.world
local order = df.manager_order:new()
order.id = world.manager_order_next_id
world.manager_order_next_id = world.manager_order_next_id + 1
order.job_type = job_type
order.frequency = df.manager_order.T_frequency.OneTime
order.amount_left = amount
order.amount_total = amount
if reaction and reaction ~= '' then
    order.reaction_name = reaction
end
world.manager_orders:insert('#', order)

print(json.encode({
    queued = job,
    amount = amount,
    orders = #world.manager_orders,
}))
