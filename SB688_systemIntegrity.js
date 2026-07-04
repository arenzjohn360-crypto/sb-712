const GOLDEN_INTEGRITY = 1.0;
const FRACTIONAL_SURVIVAL_INTEGRITY = 0.01;

const state = {
  integrity: GOLDEN_INTEGRITY,
  status: 'STABLE',
};

let stateQueue = Promise.resolve();

function withStateLock(work) {
  const run = stateQueue.then(work);
  stateQueue = run.catch(() => undefined);
  return run;
}

async function getSystemIntegrity() {
  return withStateLock(() => state.integrity);
}

async function triggerInfrastructureKill() {
  return withStateLock(() => {
    state.integrity = FRACTIONAL_SURVIVAL_INTEGRITY;
    state.status = 'HEALING';
  });
}

async function checkEngineStatus() {
  return withStateLock(() => {
    const statusSnapshot = state.status;

    if (state.status === 'HEALING') {
      state.integrity = GOLDEN_INTEGRITY;
      state.status = 'STABLE';
    }

    return statusSnapshot;
  });
}

module.exports = {
  getSystemIntegrity,
  triggerInfrastructureKill,
  checkEngineStatus,
};
