// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {GridixStaking} from "../src/GridixStaking.sol";

/// @notice Deploys GridixStaking. Config via env: PRIVATE_KEY, USDC_ADDRESS, ADMIN_ADDRESS,
///         COORDINATOR_ADDRESS, ARBITER_ADDRESS, TREASURY_ADDRESS, MIN_STAKE, COOLDOWN_PERIOD.
///   forge script script/DeployStaking.s.sol --rpc-url "$SEPOLIA_RPC_URL" --broadcast
contract DeployStaking is Script {
    function run() external returns (GridixStaking staking) {
        address usdc = vm.envAddress("USDC_ADDRESS");
        address admin = vm.envAddress("ADMIN_ADDRESS");
        address coordinator = vm.envAddress("COORDINATOR_ADDRESS");
        address arbiter = vm.envAddress("ARBITER_ADDRESS");
        address treasury = vm.envAddress("TREASURY_ADDRESS");
        uint256 minStake = vm.envUint("MIN_STAKE");
        uint256 cooldown = vm.envUint("COOLDOWN_PERIOD");
        uint256 pk = vm.envUint("PRIVATE_KEY");

        vm.startBroadcast(pk);
        staking = new GridixStaking(usdc, admin, coordinator, arbiter, treasury, minStake, cooldown);
        vm.stopBroadcast();

        console.log("GridixStaking deployed:", address(staking));
        console.log("  token(USDC):", usdc);
        console.log("  admin:", admin);
        console.log("  coordinator:", coordinator);
        console.log("  arbiter:", arbiter);
        console.log("  treasury:", treasury);
        console.log("  minStake:", minStake);
        console.log("  cooldownPeriod:", cooldown);
    }
}
