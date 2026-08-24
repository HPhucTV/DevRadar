export function localNoLoginEnabled(): boolean {
  return process.env.DEVRADAR_LOCAL_NO_LOGIN_ENABLED?.trim().toLowerCase() === "true";
}
