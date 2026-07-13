// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {GridixEscrow} from "../src/GridixEscrow.sol";

/// @notice Deploys GridixEscrow. Config via env:
///   PRIVATE_KEY          deployer key (funded with Sepolia ETH)
///   USDC_ADDRESS         the escrowed token (Circle Sepolia USDC by default in .env.example)
///   ADMIN_ADDRESS        DEFAULT_ADMIN_ROLE holder
///   COORDINATOR_ADDRESS  COORDINATOR_ROLE holder
///   TREASURY_ADDRESS     destination for debited funds
///
///   forge script script/Deploy.s.sol --rpc-url "$SEPOLIA_RPC_URL" --broadcast --verify
contract Deploy is Script {
    function run() external returns (GridixEscrow escrow) {
        address usdc = vm.envAddress("USDC_ADDRESS");
        address admin = vm.envAddress("ADMIN_ADDRESS");
        address coordinator = vm.envAddress("COORDINATOR_ADDRESS");
        address treasury = vm.envAddress("TREASURY_ADDRESS");
        uint256 pk = vm.envUint("PRIVATE_KEY");

        vm.startBroadcast(pk);
        escrow = new GridixEscrow(usdc, admin, coordinator, treasury);
        vm.stopBroadcast();

        console.log("GridixEscrow deployed:", address(escrow));
        console.log("  token (USDC):", usdc);
        console.log("  admin:", admin);
        console.log("  coordinator:", coordinator);
        console.log("  treasury:", treasury);
    }
}
