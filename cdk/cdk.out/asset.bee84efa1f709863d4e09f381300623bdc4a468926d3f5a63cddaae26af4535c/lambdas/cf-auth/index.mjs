/**
 * CloudFront Lambda@Edge — Cookie-based password auth
 * 
 * Flow:
 *   1. Any request → check for valid __lp_auth cookie
 *   2. Valid cookie → pass through to origin
 *   3. No/invalid cookie + GET → return login page
 *   4. POST /__auth with correct password → set cookie, redirect
 *
 * Password stored in Secrets Manager (us-east-1).
 * Cookie = HMAC(password, expiry) — changing password invalidates all cookies.
 * 90-day cookie TTL.
 */

import { createHmac, timingSafeEqual } from 'crypto';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

const SECRET_ID = 'life-platform/cf-auth';
const COOKIE_NAME = '__lp_auth';
const COOKIE_MAX_AGE = 90 * 24 * 60 * 60; // 90 days
const CACHE_TTL_MS = 5 * 60 * 1000;       // 5 min cache

// ── Password cache (persists across warm invocations) ──
let _cachedPassword = null;
let _cacheExpiry = 0;
const sm = new SecretsManagerClient({ region: 'us-east-1' });

async function getPassword() {
    if (_cachedPassword && Date.now() < _cacheExpiry) return _cachedPassword;
    const resp = await sm.send(new GetSecretValueCommand({ SecretId: SECRET_ID }));
    const secret = JSON.parse(resp.SecretString);
    _cachedPassword = secret.password;
    _cacheExpiry = Date.now() + CACHE_TTL_MS;
    return _cachedPassword;
}

// ── Cookie helpers ──
function hmacSign(password, expiry) {
    return createHmac('sha256', password).update(String(expiry)).digest('hex');
}

function makeCookieHeader(password) {
    const expiry = Math.floor(Date.now() / 1000) + COOKIE_MAX_AGE;
    const sig = hmacSign(password, expiry);
    return `${COOKIE_NAME}=${expiry}|${sig}; Path=/; Max-Age=${COOKIE_MAX_AGE}; Secure; HttpOnly; SameSite=Lax`;
}

function validateCookie(cookieStr, password) {
    const re = new RegExp(`${COOKIE_NAME}=(\\d+)\\|([a-f0-9]+)`);
    const m = cookieStr.match(re);
    if (!m) return false;
    const [, expiryStr, sig] = m;
    if (parseInt(expiryStr, 10) < Math.floor(Date.now() / 1000)) return false;
    const expected = hmacSign(password, expiryStr);
    // Timing-safe comparison
    try {
        return timingSafeEqual(Buffer.from(sig, 'hex'), Buffer.from(expected, 'hex'));
    } catch {
        return false;
    }
}

// ── Login page HTML ──
function loginPage(redirectUri, error) {
    const errorHtml = error
        ? '<p style="color:#ef4444;text-align:center;margin:0 0 1rem;font-size:0.9rem">Incorrect password</p>'
        : '';
    const esc = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
    const html = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Life Platform</title>
<style>
*{box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f1117;color:#e0e0e0;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}
.card{background:#1a1d27;border-radius:12px;padding:2rem;width:90%;max-width:360px;box-shadow:0 4px 24px rgba(0,0,0,.4)}
h1{font-size:1.25rem;margin:0 0 1.5rem;text-align:center;font-weight:600}
input[type=password]{width:100%;padding:12px 14px;border:1px solid #2d3040;border-radius:8px;background:#0f1117;color:#e0e0e0;font-size:1rem;margin-bottom:1rem;outline:none;transition:border .2s}
input[type=password]:focus{border-color:#3b82f6}
button{width:100%;padding:12px;border:none;border-radius:8px;background:#3b82f6;color:#fff;font-size:1rem;font-weight:500;cursor:pointer;transition:background .2s}
button:hover{background:#2563eb}
button:active{background:#1d4ed8}
</style>
</head>
<body>
<div class="card">
<h1>Life Platform</h1>
${errorHtml}
<form method="POST" action="/__auth">
<input type="password" name="password" placeholder="Password" autofocus required autocomplete="current-password">
<input type="hidden" name="redirect" value="${esc(redirectUri)}">
<button type="submit">Sign In</button>
</form>
</div>
</body>
</html>`;

    return {
        status: '200',
        statusDescription: 'OK',
        headers: {
            'content-type': [{ value: 'text/html; charset=utf-8' }],
            'cache-control': [{ value: 'no-store' }],
        },
        body: html,
    };
}

// ── Handler ──
export async function handler(event) {
    const request = event.Records[0].cf.request;
    const uri = request.uri;
    const method = request.method;
    const cookieStr = (request.headers.cookie || []).map(c => c.value).join('; ');

    let password;
    try {
        password = await getPassword();
    } catch (err) {
        // If Secrets Manager is unreachable, fail open with error page
        return {
            status: '503',
            statusDescription: 'Service Unavailable',
            headers: { 'content-type': [{ value: 'text/plain' }] },
            body: 'Auth service temporarily unavailable. Try again in a moment.',
        };
    }

    // ── Authenticated? Pass through ──
    if (validateCookie(cookieStr, password)) {
        if (uri === '/__auth') {
            return { status: '302', statusDescription: 'Found',
                     headers: { location: [{ value: '/' }], 'cache-control': [{ value: 'no-store' }] } };
        }
        return request;
    }

    // ── POST /__auth → validate password ──
    if (method === 'POST' && uri === '/__auth') {
        let body = '';
        if (request.body) {
            body = request.body.encoding === 'base64'
                ? Buffer.from(request.body.data, 'base64').toString('utf-8')
                : request.body.data;
        }
        const params = new URLSearchParams(body);
        const submitted = params.get('password') || '';
        const redirectTo = params.get('redirect') || '/';

        if (submitted === password) {
            return {
                status: '302',
                statusDescription: 'Found',
                headers: {
                    location: [{ value: redirectTo }],
                    'set-cookie': [{ value: makeCookieHeader(password) }],
                    'cache-control': [{ value: 'no-store' }],
                },
            };
        }
        return loginPage(redirectTo, true);
    }

    // ── Not authenticated → login page ──
    return loginPage(uri, false);
}
