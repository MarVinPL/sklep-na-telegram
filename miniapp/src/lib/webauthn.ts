import type { CeremonyOptions } from "./api";

function decodeBase64Url(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, "=");
  const binary = atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return bytes.buffer;
}

function encodeBase64Url(value: ArrayBuffer): string {
  const bytes = new Uint8Array(value);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

function preparePublicKey(options: CeremonyOptions["publicKey"]): PublicKeyCredentialRequestOptions | PublicKeyCredentialCreationOptions {
  const copy = structuredClone(options) as Record<string, unknown>;
  copy.challenge = decodeBase64Url(String(copy.challenge));

  if ("user" in copy && typeof copy.user === "object" && copy.user !== null) {
    const user = copy.user as Record<string, unknown>;
    user.id = decodeBase64Url(String(user.id));
  }

  for (const key of ["allowCredentials", "excludeCredentials"]) {
    const descriptors = copy[key];
    if (Array.isArray(descriptors)) {
      copy[key] = descriptors.map((item) => {
        const descriptor = item as Record<string, unknown>;
        return { ...descriptor, id: decodeBase64Url(String(descriptor.id)) };
      });
    }
  }

  return copy as unknown as PublicKeyCredentialRequestOptions | PublicKeyCredentialCreationOptions;
}

function serializeCredential(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response;
  const serialized: Record<string, unknown> = {
    id: credential.id,
    rawId: encodeBase64Url(credential.rawId),
    type: credential.type,
    clientExtensionResults: credential.getClientExtensionResults(),
    response: {
      clientDataJSON: encodeBase64Url(response.clientDataJSON),
    },
  };

  if (response instanceof AuthenticatorAttestationResponse) {
    Object.assign(serialized.response as object, {
      attestationObject: encodeBase64Url(response.attestationObject),
      transports: response.getTransports?.() ?? [],
    });
  } else if (response instanceof AuthenticatorAssertionResponse) {
    Object.assign(serialized.response as object, {
      authenticatorData: encodeBase64Url(response.authenticatorData),
      signature: encodeBase64Url(response.signature),
      userHandle: response.userHandle ? encodeBase64Url(response.userHandle) : null,
    });
  } else {
    throw new Error("Nieobsługiwany typ odpowiedzi Passkey.");
  }

  return serialized;
}

export function supportsPasskeys(): boolean {
  return (
    typeof window.PublicKeyCredential !== "undefined" &&
    typeof navigator.credentials?.create === "function" &&
    typeof navigator.credentials?.get === "function"
  );
}

export async function createPasskey(options: CeremonyOptions): Promise<Record<string, unknown>> {
  const credential = await navigator.credentials.create({
    publicKey: preparePublicKey(options.publicKey) as PublicKeyCredentialCreationOptions,
  });
  if (!(credential instanceof PublicKeyCredential)) {
    throw new Error("Authenticator nie zwrócił poświadczenia Passkey.");
  }
  return serializeCredential(credential);
}

export async function getPasskey(options: CeremonyOptions): Promise<Record<string, unknown>> {
  const credential = await navigator.credentials.get({
    publicKey: preparePublicKey(options.publicKey) as PublicKeyCredentialRequestOptions,
  });
  if (!(credential instanceof PublicKeyCredential)) {
    throw new Error("Authenticator nie zwrócił poświadczenia Passkey.");
  }
  return serializeCredential(credential);
}
