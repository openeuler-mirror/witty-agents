#!/usr/bin/env node

console.log(`
[Shennong] Package files installed successfully.
[Shennong] Next, install and start the Python services:
  npm exec -- shennong-setup install
[Shennong] Then register Shennong in OpenCode:
  npm exec -- shennong-configure install --target=opencode
`)
