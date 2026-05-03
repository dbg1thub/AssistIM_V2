const { spawn } = require("node:child_process");

function probeSpawn(label, stdio) {
  return new Promise((resolve) => {
    let child;
    let stdout = "";
    let stderr = "";

    try {
      child = spawn(process.execPath, ["--version"], { stdio });
    } catch (error) {
      resolve({
        label,
        ok: false,
        error,
        stdout,
        stderr,
      });
      return;
    }

    if (child.stdout) {
      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString();
      });
    }

    if (child.stderr) {
      child.stderr.on("data", (chunk) => {
        stderr += chunk.toString();
      });
    }

    child.on("error", (error) => {
      resolve({
        label,
        ok: false,
        error,
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      });
    });

    child.on("close", (code) => {
      resolve({
        label,
        ok: code === 0,
        code,
        stdout: stdout.trim(),
        stderr: stderr.trim(),
      });
    });
  });
}

async function main() {
  console.log("AssistIM admin-web doctor");
  console.log(`cwd: ${process.cwd()}`);
  console.log(`node: ${process.execPath}`);
  console.log(`version: ${process.version}`);
  console.log(`platform: ${process.platform} ${process.arch}`);

  const inherited = await probeSpawn("spawn inherit stdio", "inherit");
  if (!inherited.ok) {
    console.error(`\n[FAIL] ${inherited.label}`);
    console.error(inherited.error ? inherited.error.message : `exit code ${inherited.code}`);
    process.exitCode = 1;
    return;
  }
  console.log(`\n[OK] ${inherited.label}`);

  const piped = await probeSpawn("spawn pipe stdio", ["ignore", "pipe", "pipe"]);
  if (!piped.ok) {
    console.error(`\n[FAIL] ${piped.label}`);
    console.error(piped.error ? piped.error.message : `exit code ${piped.code}`);
    if (piped.stderr) {
      console.error(piped.stderr);
    }
    console.error(
      "\nVite, Vitest, and esbuild require child_process.spawn with pipe stdio. " +
        "They will fail with spawn EPERM while this probe fails."
    );
    process.exitCode = 1;
    return;
  }

  console.log(`[OK] ${piped.label}: ${piped.stdout || "completed"}`);
  console.log("\nEnvironment can run Vite/Vitest child-process probes.");
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
