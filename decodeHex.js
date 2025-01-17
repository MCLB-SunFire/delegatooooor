const BN = require('bn.js');

// Get the hex data from the command-line arguments
const hexData = process.argv[2];
if (!hexData) {
  console.error("Hex data argument is required.");
  process.exit(1);
}

/**
 * Decode hex data for the staking contract.
 * @param {string} hexData - The hex-encoded transaction data.
 * @returns {object} Decoded data including validatorId and token amount.
 */
function decodeHexData(hexData) {
  // Break the data into 32-byte chunks (skipping function selector)
  const params = hexData.slice(10).match(/.{1,64}/g);

  // Decode the parameters as 256-bit integers
  const decodedParams = params.map(param => new BN(param, 16));

  // Extract simplified fields
  const validatorId = decodedParams[0].toString(); // First parameter
  const amountInTokens = decodedParams[1].div(new BN('1000000000000000000')).toString(); // Convert to tokens

  return {
    validatorId,
    amountInTokens,
  };
}

// Decode and output the result
const result = decodeHexData(hexData);
console.log(JSON.stringify(result));
