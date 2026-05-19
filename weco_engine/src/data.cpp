/*

Association Scientifique pour la Geologie et ses Applications (ASGA)

Copyright (c) 2018 ASGA. All Rights Reserved.

This program is a Trade Secret of the ASGA and it is not to be:
 * reproduced, published, or disclosed to other,
 * distributed or displayed,
 * used for purposes or on Sites other than described in the GOCAD Advancement Agreement,
   without the prior written authorization of the ASGA.

Licencee agrees to attach or embed this Notice on all copies of the program,
including partial copies or modified versions thereof.

*/

#include <weco.h>
#include <weco/datareader.h>



namespace WeCo {


//========================== DataStore =====================================

bool DataStore::data_exists(const std::string & name) const {
	for(const auto &i : datas_) {
		if(i.name() == name) return true;
	}
	return false;
}

const DataStore::Data & DataStore::get_data(const std::string & name) const {
	assert(data_exists(name));
	for(const auto &i : datas_) {
		if(i.name() == name) return i;
	}
	throw Exception("Data Not Found");
}

bool DataStore::read(DataReader&data_reader ) {
	clear();

	int size = data_reader.read_int(0,1000000);
	datas_.reserve(size);
	for (;size>0;size--) datas_.emplace_back(data_reader);
	return data_reader.ok();
}
void DataStore::clear() {
	datas_.clear();
}


std::vector<std::string> DataStore::data_names()const {
	std::vector<std::string> result;
	result.reserve(datas_.size());
	for(const Data& data : datas_)
		result.push_back(data.name());
	return result;
}


//========================== DataStore::Data =====================================
bool DataStore::Data::read(DataReader&data_reader ) {
	data_.clear();
	name_ = data_reader.read_string();
	int size = data_reader.read_int(1,1000000);
	data_.reserve(size);
	for (;size>0;size--) data_.push_back(data_reader.read_value());
	return data_reader.ok();
}





//================== RegionList ===============================================

void RegionList::read(DataReader &reader){
	name_ = reader.read_string();
	for(int nbr_value = reader.read_int();nbr_value>0;nbr_value--) {
		unsigned id = (unsigned)reader.read_int(0,500000);
		unsigned start = (unsigned)reader.read_int(0,500000);
		unsigned length = (unsigned)reader.read_int(0,500000);
		add(id,start,length);
	}

}

//==================== Well ===================================================
Well::Well(DataReader&data_reader) {
	read(data_reader);

}


bool Well::read(DataReader&data_reader){
	clear();
	well_name_ = data_reader.read_string();
	well_size_ = (unsigned)data_reader.read_int(2,100000);
	x_ = data_reader.read_value();
	y_ = data_reader.read_value();
	z_ = data_reader.read_value();
	h_ = data_reader.read_value();

	if(!data_reader.ok())return false;

	if(!DataStore::read(data_reader)) return false;

	if(data_reader.file_version()>=2) {
		//read region list
		int nbr_rl = data_reader.read_int();
		for (int i=0;i<nbr_rl;i++)
			region_lists_.emplace_back(data_reader);
	}

	return data_reader.ok();

}

void Well::clear() {
	well_name_ = "NONAME";

}
const RegionList & Well::get_region_list(const std::string & name) const{
	assert(region_list_exists(name));
	for(const auto &i : region_lists_) {
		if(i.name() == name) return i;
	}
	throw Exception("Data Not Found");
}

bool Well::region_list_exists(const std::string & name) const {
	for(const auto &i : region_lists_) {
		if(i.name() == name) return true;
	}
	return false;
}

std::vector<std::string> Well::region_list_names()const{
	std::vector<std::string> result;
	result.reserve(region_lists_.size());
	for(const RegionList& data : region_lists_)
		result.push_back(data.name());
	return result;
}


//================================= Well List ========================================


/// default Constructor
WellList::WellList(){

}

/// Create from file
WellList::WellList(const std::string & filename)
	: WellList() {
		DataReader reader(filename,"WellList");
		read(reader);
		reader.check_end();
}


WellList& WellList::operator = (const WellList &wl){
	wells_.clear();
	wells_.reserve(wl.nbr_wells());
	for(auto const& w:wl.wells_ ) {
		wells_.emplace_back(new Well(*w));
	}
	return *this;
}

void WellList::add(const Well& well) {
	wells_.emplace_back(new Well(well));
	wells_.back()->set_well_id(wells_.size()-1);
}



// Create from DataReader
WellList::WellList(DataReader & data_reader):
		WellList(){
	read(data_reader);

}



/// Read a well list
bool WellList::read(const std::string& filename){
	DataReader reader(filename);
	return read(reader) && reader.check_end();
}



/// Read a well list
bool WellList::read(DataReader & data_reader){
	wells_.clear();
	int size = data_reader.read_int(0,1000000);
	wells_.reserve(size);
	for (;size>0;size--) wells_.emplace_back(new Well(data_reader));

	if(!data_reader.ok()) return false;

	set_well_id();

	return data_reader.ok();

}

void WellList::set_well_id() {
	for (WellId id =0;id<wells_.size();id++)
		wells_[id]->set_well_id(id);
}

void WellList::convert(std::vector<Well*>&to)const{
	to.reserve(nbr_wells());
	for(auto &i: wells_)
		to.push_back(i.get());
}

}



