package com.example.springwebtlias.service;

import com.example.springwebtlias.mapper.EmpMapper;
import com.example.springwebtlias.pojo.Emp;
import com.example.springwebtlias.pojo.PageBean;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

@Service
public interface EmpService {

    PageBean selectByPage(Integer page, Integer pageSize,String name,Short gender,LocalDateTime begin,LocalDateTime end);


    void delete(List<Integer> ids);

    void save(Emp emp);
}
