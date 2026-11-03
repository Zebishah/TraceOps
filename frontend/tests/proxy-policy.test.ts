import test from 'node:test';
import assert from 'node:assert/strict';
import {allowedBackendPath,cookieLifetime,sameOrigin} from '../lib/product/proxy-policy.ts';
const org='d5d2a37c-5538-4783-8f42-a285d8534b7a';
test('allows only intended backend operations',()=>{assert.equal(allowedBackendPath(`organizations/${org}/incidents`),true);assert.equal(allowedBackendPath(`organizations/${org}/dashboard/resources/documents/${org}`),true);assert.equal(allowedBackendPath('auth/me'),true);assert.equal(allowedBackendPath('health/ready'),true);});
test('rejects arbitrary hosts, traversal and encoded separators',()=>{for(const value of ['https://example.com/','../auth/me','auth/%2fme','auth/me?token=secret','organizations/not-a-uuid/incidents','admin/delete-all'])assert.equal(allowedBackendPath(value),false,value);});
test('mutations require the exact request origin',()=>{assert.equal(sameOrigin('https://product.example/api/backend/auth/login','https://product.example'),true);assert.equal(sameOrigin('https://product.example/api/backend/auth/login','https://attacker.example'),false);assert.equal(sameOrigin('https://product.example/api/backend/auth/login',null),false);});
test('session retention is bounded even for a distant expiry',()=>{const token='header.'+btoa(JSON.stringify({exp:Math.floor(Date.now()/1000)+900000}))+'.signature';assert.equal(cookieLifetime(token),86400);assert.equal(cookieLifetime('malformed'),3600);});
