-- agent/cursor - report the map cursor as JSON
local json = require('json')
local c = df.global.cursor
print(json.encode({ x = c.x, y = c.y, z = c.z }))
