/**
 * Client-side JWT payload decode - NOT verification. This never checks
 * the signature (it can't; the signing secret never leaves the gateway),
 * so it must only ever be used for UX decisions (which nav links to
 * show, which route to redirect to) - never as a substitute for the
 * gateway's own auth.get_current_user()/require_role(), which is what
 * actually enforces access on every request regardless of what this
 * decodes. A tampered or expired token decoded here just produces a
 * worse UX (wrong nav shown), not a security hole, since every API call
 * still goes through the real check server-side.
 */

function _base64UrlDecode(segment) {
  const padded = segment.replace(/-/g, '+').replace(/_/g, '/').padEnd(Math.ceil(segment.length / 4) * 4, '=')
  return atob(padded)
}

/**
 * @param {string} token
 * @returns {{ userId: string, username: string, role: string, regionId: string | null, exp: number } | null}
 *   null if the token is malformed or already expired.
 */
export function decodeToken(token) {
  if (!token) return null
  const parts = token.split('.')
  if (parts.length !== 3) return null

  let payload
  try {
    payload = JSON.parse(_base64UrlDecode(parts[1]))
  } catch {
    return null
  }

  if (typeof payload.exp === 'number' && Date.now() >= payload.exp * 1000) {
    return null // expired - treat exactly like "no token"
  }

  return {
    userId: payload.user_id,
    username: payload.username,
    role: payload.role,
    regionId: payload.region_id ?? null,
    exp: payload.exp,
  }
}
