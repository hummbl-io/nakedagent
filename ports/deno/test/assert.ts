// Minimal assertions built on node:assert so the port needs no jsr:@std/assert import.
import nodeAssert from "node:assert/strict";

export function assert(cond: unknown, message?: string): asserts cond {
  nodeAssert.ok(cond, message);
}

export function assertFalse(cond: unknown, message?: string): void {
  nodeAssert.ok(!cond, message);
}

export function assertEquals<T>(actual: T, expected: T, message?: string): void {
  nodeAssert.equal(actual, expected, message);
}

export function assertDeepEqual(actual: unknown, expected: unknown, message?: string): void {
  nodeAssert.deepEqual(actual, expected, message);
}
