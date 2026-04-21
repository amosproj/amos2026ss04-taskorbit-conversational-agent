const express = require('express');
const healthRoute = require('./routes/health');
const agentRoute = require('./routes/agent');

const app = express();

app.use(express.json());

app.use('/health', healthRoute);
app.use('/agent', agentRoute);

module.exports = app;