// _pyre_native — PYRE's blessed native crypto module for Kybra canisters.
//
// This file is compiled INSIDE the Kybra-generated canister crate: the
// scripts/build_native.sh pipeline copies it to .kybra/<canister>/src/
// pyre_native.rs, declares `mod pyre_native;` in the generated lib.rs, and
// registers `_pyre_native` on the RustPython VM next to the stdlib modules
// (see the add_native_module lines the script inserts).
//
// Scope is deliberately tiny: AEAD seal/open only, wrapping the audited
// RustCrypto crates (aes-gcm, chacha20poly1305). No key generation, no
// nonce generation, no defaults — misuse resistance lives in the Python
// layer (pyre/crypto.py). Hashing/HMAC are NOT here because RustPython's
// native hashlib/hmac already provide them (v1.1 Phase-0 audit).
//
// All functions raise ValueError on bad input sizes or authentication
// failure; pyre/crypto.py maps these to PyreError subclasses.

use rustpython_derive::pymodule;

#[pymodule]
pub mod _pyre_native {
    use aes_gcm::aead::{Aead, KeyInit, Payload};
    use aes_gcm::Aes256Gcm;
    use chacha20poly1305::ChaCha20Poly1305;
    use rustpython_vm::function::ArgBytesLike;
    use rustpython_vm::{PyResult, VirtualMachine};

    const KEY_LEN: usize = 32;
    const NONCE_LEN: usize = 12;

    #[pyattr]
    const VERSION: &str = "1";

    /// BLAKE3, 32-byte digest. Included because its measured wasm cost is
    /// tiny (raw +15KB / gz +4KB); RustPython's native hashlib covers
    /// everything else (sha2/sha3/blake2) but not blake3.
    #[pyfunction]
    fn blake3_hash(data: ArgBytesLike, _vm: &VirtualMachine) -> Vec<u8> {
        data.with_ref(|b| blake3::hash(b).as_bytes().to_vec())
    }

    /// Variable-output BLAKE2b (1..=64 byte digests). RustPython's native
    /// hashlib.blake2b is the FIXED 64-byte variant only — it rejects the
    /// digest_size kwarg — so pyre.crypto routes non-64 sizes here. The
    /// blake2 crate is already in the canister's dependency graph (it
    /// implements hashlib itself), so this costs ~nothing in wasm size.
    #[pyfunction]
    fn blake2b_var(
        data: ArgBytesLike,
        digest_size: usize,
        vm: &VirtualMachine,
    ) -> PyResult<Vec<u8>> {
        use blake2::digest::{Update, VariableOutput};
        let mut hasher = blake2::Blake2bVar::new(digest_size).map_err(|_| {
            vm.new_value_error(format!(
                "_pyre_native: blake2b digest_size must be 1..=64, got {}",
                digest_size
            ))
        })?;
        data.with_ref(|b| hasher.update(b));
        let mut out = vec![0u8; digest_size];
        hasher
            .finalize_variable(&mut out)
            .map_err(|_| vm.new_value_error("_pyre_native: blake2b failed".to_owned()))?;
        Ok(out)
    }

    /// RS256 — RSASSA-PKCS1-v1_5 signature verification over SHA-256.
    ///
    /// Entropy-free and deterministic: no getrandom, no key generation.
    /// Inputs are exactly what a JWKS entry gives you, base64url-decoded:
    ///   n         RSA modulus, big-endian bytes
    ///   e         RSA public exponent, big-endian bytes (usually 0x010001)
    ///   message   the JWT signing input (ASCII "<header>.<payload>")
    ///   signature the JWT signature bytes
    /// Returns True iff the signature is valid. Malformed key material
    /// (e.g. an absurd modulus) raises ValueError; a well-formed but wrong
    /// signature returns False — the caller distinguishes "can't check" from
    /// "checked, invalid".
    #[pyfunction]
    fn rsa_pkcs1v15_verify_sha256(
        n: ArgBytesLike,
        e: ArgBytesLike,
        message: ArgBytesLike,
        signature: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<bool> {
        use rsa::{BigUint, Pkcs1v15Sign, RsaPublicKey};
        use sha2::{Digest, Sha256};

        let n = n.with_ref(|b| b.to_vec());
        let e = e.with_ref(|b| b.to_vec());
        let message = message.with_ref(|b| b.to_vec());
        let signature = signature.with_ref(|b| b.to_vec());

        let modulus = BigUint::from_bytes_be(&n);
        let exponent = BigUint::from_bytes_be(&e);
        let key = RsaPublicKey::new(modulus, exponent).map_err(|err| {
            vm.new_value_error(format!("_pyre_native: invalid RSA public key: {}", err))
        })?;

        let hashed = Sha256::digest(&message);
        let scheme = Pkcs1v15Sign::new::<Sha256>();
        Ok(key.verify(scheme, &hashed, &signature).is_ok())
    }

    /// ES256 — ECDSA over NIST P-256 (secp256r1) with SHA-256.
    ///
    /// Also entropy-free. Inputs from a JWKS EC entry, base64url-decoded:
    ///   x, y      the 32-byte affine coordinates of the public point
    ///   message   the JWT signing input
    ///   signature the 64-byte raw r||s JWT signature
    /// Returns True iff valid. Malformed point/signature raises ValueError.
    #[pyfunction]
    fn ecdsa_p256_verify_sha256(
        x: ArgBytesLike,
        y: ArgBytesLike,
        message: ArgBytesLike,
        signature: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<bool> {
        use p256::ecdsa::signature::Verifier;
        use p256::ecdsa::{Signature, VerifyingKey};
        use p256::elliptic_curve::generic_array::GenericArray;
        use p256::EncodedPoint;

        let x = x.with_ref(|b| b.to_vec());
        let y = y.with_ref(|b| b.to_vec());
        let message = message.with_ref(|b| b.to_vec());
        let signature = signature.with_ref(|b| b.to_vec());

        if x.len() != 32 || y.len() != 32 {
            return Err(vm.new_value_error(format!(
                "_pyre_native: ES256 x/y must be 32 bytes each, got {}/{}",
                x.len(),
                y.len()
            )));
        }
        let point = EncodedPoint::from_affine_coordinates(
            GenericArray::from_slice(&x),
            GenericArray::from_slice(&y),
            false,
        );
        let key = VerifyingKey::from_encoded_point(&point).map_err(|err| {
            vm.new_value_error(format!("_pyre_native: invalid P-256 public key: {}", err))
        })?;
        let sig = Signature::from_slice(&signature).map_err(|err| {
            vm.new_value_error(format!("_pyre_native: invalid ES256 signature: {}", err))
        })?;
        Ok(key.verify(&message, &sig).is_ok())
    }

    fn check_key_nonce(key: &[u8], nonce: &[u8], vm: &VirtualMachine) -> PyResult<()> {
        if key.len() != KEY_LEN {
            return Err(vm.new_value_error(format!(
                "_pyre_native: key must be exactly {} bytes, got {}",
                KEY_LEN,
                key.len()
            )));
        }
        if nonce.len() != NONCE_LEN {
            return Err(vm.new_value_error(format!(
                "_pyre_native: nonce must be exactly {} bytes, got {}",
                NONCE_LEN,
                nonce.len()
            )));
        }
        Ok(())
    }

    fn seal<C: Aead + KeyInit>(
        name: &str,
        key: ArgBytesLike,
        nonce: ArgBytesLike,
        plaintext: ArgBytesLike,
        aad: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<Vec<u8>> {
        let key = key.with_ref(|b| b.to_vec());
        let nonce = nonce.with_ref(|b| b.to_vec());
        let plaintext = plaintext.with_ref(|b| b.to_vec());
        let aad = aad.with_ref(|b| b.to_vec());
        check_key_nonce(&key, &nonce, vm)?;
        let cipher = C::new_from_slice(&key)
            .map_err(|_| vm.new_value_error(format!("_pyre_native: bad {} key", name)))?;
        cipher
            .encrypt(
                nonce.as_slice().into(),
                Payload {
                    msg: &plaintext,
                    aad: &aad,
                },
            )
            .map_err(|_| vm.new_value_error(format!("_pyre_native: {} encryption failed", name)))
    }

    fn open<C: Aead + KeyInit>(
        name: &str,
        key: ArgBytesLike,
        nonce: ArgBytesLike,
        ciphertext: ArgBytesLike,
        aad: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<Vec<u8>> {
        let key = key.with_ref(|b| b.to_vec());
        let nonce = nonce.with_ref(|b| b.to_vec());
        let ciphertext = ciphertext.with_ref(|b| b.to_vec());
        let aad = aad.with_ref(|b| b.to_vec());
        check_key_nonce(&key, &nonce, vm)?;
        let cipher = C::new_from_slice(&key)
            .map_err(|_| vm.new_value_error(format!("_pyre_native: bad {} key", name)))?;
        cipher
            .decrypt(
                nonce.as_slice().into(),
                Payload {
                    msg: &ciphertext,
                    aad: &aad,
                },
            )
            .map_err(|_| {
                vm.new_value_error(format!(
                    "_pyre_native: {} authentication failed (wrong key, tampered ciphertext, or aad mismatch)",
                    name
                ))
            })
    }

    /// AES-256-GCM seal: returns ciphertext||tag (tag = 16 bytes).
    /// key must be 32 bytes, nonce 12 bytes, and the (key, nonce) pair
    /// MUST be unique per message — the caller (pyre.crypto) guarantees it.
    #[pyfunction]
    fn aes256_gcm_seal(
        key: ArgBytesLike,
        nonce: ArgBytesLike,
        plaintext: ArgBytesLike,
        aad: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<Vec<u8>> {
        seal::<Aes256Gcm>("AES-256-GCM", key, nonce, plaintext, aad, vm)
    }

    /// AES-256-GCM open: input is ciphertext||tag; raises ValueError on
    /// authentication failure.
    #[pyfunction]
    fn aes256_gcm_open(
        key: ArgBytesLike,
        nonce: ArgBytesLike,
        ciphertext: ArgBytesLike,
        aad: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<Vec<u8>> {
        open::<Aes256Gcm>("AES-256-GCM", key, nonce, ciphertext, aad, vm)
    }

    /// ChaCha20-Poly1305 (RFC 8439) seal: returns ciphertext||tag.
    #[pyfunction]
    fn chacha20poly1305_seal(
        key: ArgBytesLike,
        nonce: ArgBytesLike,
        plaintext: ArgBytesLike,
        aad: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<Vec<u8>> {
        seal::<ChaCha20Poly1305>("ChaCha20-Poly1305", key, nonce, plaintext, aad, vm)
    }

    /// ChaCha20-Poly1305 open: input is ciphertext||tag; raises ValueError
    /// on authentication failure.
    #[pyfunction]
    fn chacha20poly1305_open(
        key: ArgBytesLike,
        nonce: ArgBytesLike,
        ciphertext: ArgBytesLike,
        aad: ArgBytesLike,
        vm: &VirtualMachine,
    ) -> PyResult<Vec<u8>> {
        open::<ChaCha20Poly1305>("ChaCha20-Poly1305", key, nonce, ciphertext, aad, vm)
    }
}
