"""Attempt to provision an Oracle Cloud Always Free ARM instance.

Runs on a schedule from GitHub Actions. Exits cleanly on capacity errors
so the next scheduled run can try again. Exits 0 once an instance exists.

Required env vars (set as GitHub Secrets):
    OCI_USER_OCID
    OCI_TENANCY_OCID
    OCI_FINGERPRINT
    OCI_REGION                 (e.g. us-ashburn-1)
    OCI_PRIVATE_KEY            (full PEM contents)
    OCI_COMPARTMENT_OCID       (where to create the instance)
    OCI_SUBNET_OCID            (pre-created public subnet)
    OCI_IMAGE_OCID             (Ubuntu 22.04 ARM image)
    OCI_SSH_PUBLIC_KEY         (one-line ssh-rsa ... )

Optional:
    OCI_INSTANCE_NAME          (default: warehouse-vm)
    OCI_OCPUS                  (default: 4)
    OCI_MEMORY_GB              (default: 24)
    OCI_BOOT_VOLUME_GB         (default: 200)
"""
import os
import sys
import tempfile

import oci


CAPACITY_ERROR_HINTS = ("capacity", "out of host capacity", "outofcapacity")


def _build_config():
    key = os.environ["OCI_PRIVATE_KEY"]
    fp = tempfile.NamedTemporaryFile(suffix=".pem", delete=False, mode="w")
    fp.write(key)
    fp.close()
    return {
        "user": os.environ["OCI_USER_OCID"],
        "tenancy": os.environ["OCI_TENANCY_OCID"],
        "fingerprint": os.environ["OCI_FINGERPRINT"],
        "region": os.environ["OCI_REGION"],
        "key_file": fp.name,
    }


def _existing_instance(compute, compartment_id, name):
    insts = oci.pagination.list_call_get_all_results(
        compute.list_instances, compartment_id
    ).data
    for i in insts:
        if i.lifecycle_state in ("RUNNING", "PROVISIONING", "STARTING") and i.display_name == name:
            return i
    return None


def main():
    config = _build_config()
    compute = oci.core.ComputeClient(config)
    identity = oci.identity.IdentityClient(config)

    compartment = os.environ["OCI_COMPARTMENT_OCID"]
    subnet = os.environ["OCI_SUBNET_OCID"]
    image = os.environ["OCI_IMAGE_OCID"]
    ssh_pub = os.environ["OCI_SSH_PUBLIC_KEY"]
    name = os.getenv("OCI_INSTANCE_NAME", "warehouse-vm")
    ocpus = int(os.getenv("OCI_OCPUS", "4"))
    memory = int(os.getenv("OCI_MEMORY_GB", "24"))
    boot = int(os.getenv("OCI_BOOT_VOLUME_GB", "200"))

    existing = _existing_instance(compute, compartment, name)
    if existing:
        print(f"Instance '{name}' already exists: state={existing.lifecycle_state} id={existing.id}")
        print("Nothing to do.")
        return 0

    ads = identity.list_availability_domains(compartment).data
    print(f"Trying to provision '{name}' (A1.Flex {ocpus} OCPU / {memory} GB) across {len(ads)} ADs...")

    last_error = None
    for ad in ads:
        details = oci.core.models.LaunchInstanceDetails(
            compartment_id=compartment,
            availability_domain=ad.name,
            shape="VM.Standard.A1.Flex",
            shape_config=oci.core.models.LaunchInstanceShapeConfigDetails(
                ocpus=ocpus,
                memory_in_gbs=memory,
            ),
            create_vnic_details=oci.core.models.CreateVnicDetails(
                subnet_id=subnet,
                assign_public_ip=True,
            ),
            source_details=oci.core.models.InstanceSourceViaImageDetails(
                image_id=image,
                boot_volume_size_in_gbs=boot,
            ),
            metadata={"ssh_authorized_keys": ssh_pub},
            display_name=name,
        )
        try:
            inst = compute.launch_instance(details).data
            print(f"SUCCESS in {ad.name}: instance OCID = {inst.id}")
            print(f"State: {inst.lifecycle_state}")
            return 0
        except oci.exceptions.ServiceError as e:
            msg = (e.message or "").lower()
            is_capacity = (
                e.status == 500
                or e.code in ("OutOfCapacity", "InternalError", "TooManyRequests")
                or any(h in msg for h in CAPACITY_ERROR_HINTS)
            )
            if is_capacity:
                print(f"  {ad.name}: out of capacity ({e.code})")
                last_error = e
                continue
            # Non-capacity error — surface immediately
            print(f"  {ad.name}: ERROR code={e.code} status={e.status}: {e.message}")
            raise

    print("All ADs out of capacity. Will retry on next scheduled run.")
    if last_error:
        print(f"Last error: {last_error.code} - {last_error.message}")
    # Exit 0 so the workflow shows green (capacity isn't a failure of our code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
