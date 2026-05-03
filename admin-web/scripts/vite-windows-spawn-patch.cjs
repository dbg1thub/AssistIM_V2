const childProcess = require("child_process");

const originalExec = childProcess.exec;

childProcess.exec = function patchedExec(command, options, callback) {
  const normalizedCommand = String(command || "").trim().toLowerCase();
  if (process.platform === "win32" && normalizedCommand === "net use") {
    const done = typeof options === "function" ? options : callback;
    if (typeof done === "function") {
      process.nextTick(() => done(new Error("net use disabled for local Vite runs"), "", ""));
    }
    return {
      on() {
        return this;
      },
      kill() {
        return true;
      }
    };
  }
  return originalExec.apply(this, arguments);
};
