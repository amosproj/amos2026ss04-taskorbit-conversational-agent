const express = require('express');
const router = express.Router();

router.post('/', (req, res) => {
  res.json({ message: 'Agent endpoint placeholder' });
});

module.exports = router;