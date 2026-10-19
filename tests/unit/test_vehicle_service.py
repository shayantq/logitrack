"""تست‌های واحد سرویس ناوگان (Vehicle Service)."""
import pytest

from app.models import User, RoleEnum
from app.schemas.vehicle import VehicleRequest, VehicleStatusRequest
from app.services import vehicle_service
from app.services.exceptions import ConflictError, ForbiddenError, NotFoundError


def _make_driver(db, tag="", city=None):
    driver = User(username=f"driver_{tag}", email=f"driver_{tag}@test.local", role=RoleEnum.DRIVER, hashed_password="x", city=city)
    db.add(driver)
    db.commit()
    db.refresh(driver)
    return driver


def _make_admin(db, tag=""):
    admin = User(username=f"admin_{tag}", email=f"admin_{tag}@test.local", role=RoleEnum.ORG_ADMIN, hashed_password="x")
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return admin


def test_create_vehicle_success(db_session):
    admin = _make_admin(db_session, "1")
    driver = _make_driver(db_session, "1")
    vehicle = vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
        license_plate="AAA-111", vehicle_type="van", vehicle_name="پژو ۴۰۵",
        capacity_kg=1000, vehicle_status="available", driver_id=driver.id
    ))
    assert vehicle.driver_id == driver.id
    assert vehicle.model == "پژو ۴۰۵"


def test_create_vehicle_duplicate_plate_rejected(db_session):
    admin = _make_admin(db_session, "2")
    driver = _make_driver(db_session, "2")
    vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
        license_plate="DUP-PLATE", vehicle_type="van", vehicle_name="ون",
        capacity_kg=1000, vehicle_status="available", driver_id=driver.id
    ))
    with pytest.raises(ConflictError):
        vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
            license_plate="DUP-PLATE", vehicle_type="truck", vehicle_name="کامیون",
            capacity_kg=5000, vehicle_status="available", driver_id=driver.id
        ))


def test_only_admin_can_create_vehicle(db_session):
    driver = _make_driver(db_session, "3")
    with pytest.raises(ForbiddenError):
        vehicle_service.create_vehicle(db_session, driver, VehicleRequest(
            license_plate="X-1", vehicle_type="van", vehicle_name="ون",
            capacity_kg=1000, vehicle_status="available", driver_id=driver.id
        ))


def test_driver_can_update_own_vehicle_status(db_session):
    admin = _make_admin(db_session, "4")
    driver = _make_driver(db_session, "4")
    vehicle = vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
        license_plate="OWN-1", vehicle_type="van", vehicle_name="ون",
        capacity_kg=1000, vehicle_status="available", driver_id=driver.id
    ))
    updated = vehicle_service.update_vehicle_status(db_session, driver, vehicle.id, VehicleStatusRequest(vehicle_status="on_route"))
    assert updated.status == "on_route"


def test_driver_cannot_update_other_drivers_vehicle(db_session):
    admin = _make_admin(db_session, "5")
    driver1 = _make_driver(db_session, "owner")
    driver2 = _make_driver(db_session, "other")
    vehicle = vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
        license_plate="OTH-1", vehicle_type="van", vehicle_name="ون",
        capacity_kg=1000, vehicle_status="available", driver_id=driver1.id
    ))
    with pytest.raises(ForbiddenError):
        vehicle_service.update_vehicle_status(db_session, driver2, vehicle.id, VehicleStatusRequest(vehicle_status="on_route"))


def test_update_status_same_value_rejected(db_session):
    admin = _make_admin(db_session, "6")
    driver = _make_driver(db_session, "6")
    vehicle = vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
        license_plate="SAME-1", vehicle_type="van", vehicle_name="ون",
        capacity_kg=1000, vehicle_status="available", driver_id=driver.id
    ))
    with pytest.raises(ConflictError):
        vehicle_service.update_vehicle_status(db_session, admin, vehicle.id, VehicleStatusRequest(vehicle_status="available"))


def test_vehicle_not_found(db_session):
    admin = _make_admin(db_session, "7")
    with pytest.raises(NotFoundError):
        vehicle_service.update_vehicle_status(db_session, admin, 9999, VehicleStatusRequest(vehicle_status="available"))


def test_list_vehicles_scoped_to_driver(db_session):
    admin = _make_admin(db_session, "8")
    driver1 = _make_driver(db_session, "list1")
    driver2 = _make_driver(db_session, "list2")
    vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
        license_plate="L-1", vehicle_type="van", vehicle_name="ون۱", capacity_kg=1000, vehicle_status="available", driver_id=driver1.id
    ))
    vehicle_service.create_vehicle(db_session, admin, VehicleRequest(
        license_plate="L-2", vehicle_type="van", vehicle_name="ون۲", capacity_kg=1000, vehicle_status="available", driver_id=driver2.id
    ))

    visible_to_driver1 = vehicle_service.list_vehicles(db_session, driver1)
    assert len(visible_to_driver1) == 1
    assert visible_to_driver1[0].driver_id == driver1.id
